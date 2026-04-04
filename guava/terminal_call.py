import json
import logging
import guava
import asyncio

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer, MediaStreamTrack
from guava.devaudio.sounddevice import SoundDeviceAudioPlayer, SoundDeviceMicrophoneTrack
from aiortc.sdp import candidate_from_sdp

logger = logging.getLogger(__name__)


class TerminalCall:
    def __init__(self, client: guava.Client, webrtc_code: str):
        self._client = client
        self._webrtc_code = webrtc_code
        self._audio_player = SoundDeviceAudioPlayer()
        
    async def process_ws_messages(self, ws):
        try:
            while True:
                message = json.loads(await ws.recv())
                if message['type'] == 'answer':
                    logger.info("Setting answer...")
                    answer = RTCSessionDescription(sdp=message["answer"]["sdp"], type=message["answer"]["type"])
                    await self.pc.setRemoteDescription(answer)
        except ConnectionClosed:
            logger.info("Websocket connection closed...")

    async def drain_track(self, track: MediaStreamTrack):
        while True:
            frame = await track.recv()
            self._audio_player.add_frame(frame) # type: ignore
        
    async def start(self):
        self._audio_player.start()
        
        async with connect(self._client.get_websocket_url("webrtc/")) as ws:
            # Send auth request and wait for the auth response.
            await ws.send(json.dumps({
                "type": "auth",
                "body": self._webrtc_code
            }))

            msg = json.loads(await ws.recv())
            assert msg["type"] == "auth"
            assert msg["body"] == "OK"

            await ws.send(json.dumps({
                "type": "connect",
                "body": {}
            }))

            # Load ICE servers.
            ice_servers = []
            for s in msg["ice_servers"]:
                ice_servers.append(RTCIceServer(
                    urls=s.get("urls"),
                    username=s.get("username"),
                    credential=s.get("credential"),
                ))

            logger.info("ICE servers: %r", ice_servers)

            configuration = RTCConfiguration(iceServers=ice_servers)
            self.pc = pc = RTCPeerConnection(configuration)

            pc.addTrack(SoundDeviceMicrophoneTrack())

            await pc.setLocalDescription(await pc.createOffer())

            await ws.send(json.dumps(
                {
                    "type": "desc",
                    "body": {
                        "sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type
                    }
                }
            ))

            @pc.on("connectionstatechange")
            async def on_connectionstatechange():
                logger.info("Connection state is %s", pc.connectionState)

            @pc.on("track")
            async def on_track(track: MediaStreamTrack):
                logger.info("Track received: %s", track.kind)

                if track.kind == "audio":
                    asyncio.create_task(self.drain_track(track))

            try:
                while True:
                    message = json.loads(await ws.recv())
                    logger.debug("Received signaling socket message: %s", message)
                    if message['type'] == 'desc':
                        logger.debug("Setting answer...")
                        answer = RTCSessionDescription(sdp=message["body"]["sdp"], type=message["body"]["type"])
                        await self.pc.setRemoteDescription(answer)
                    if message["type"] == "candidate":
                        logger.debug("Addding ICE candidate...")
                        candidate = candidate_from_sdp(message['body']['candidate'])
                        candidate.sdpMid = message['body']['sdpMid']
                        candidate.sdpMLineIndex = message['body']['sdpMLineIndex']
                        await pc.addIceCandidate(candidate)
            finally:
                logger.info("Closing peer connection...")
                await pc.close()
