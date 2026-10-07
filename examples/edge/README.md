# Edge examples

These examples run entirely on-device (speech recognition, LLM and voice). They need `guava-sdk[wakeword]` and the Guava Edge runtime, and start the local guava-edge server themselves, so no API key or `guava run` is needed.

```bash
pip install "guava-sdk[wakeword]"
guava edge install          # one-off: binaries
guava edge install models   # one-off: the on-device models
python -m guava.examples.edge.plant
```

On macOS, PyAudio also needs PortAudio: `brew install portaudio`.

- [plant.py](./plant.py) - A sensor-triggered example where a house plant tracks its soil moisture (simulated off a Raspberry Pi) and asks for water when it gets dry, using a custom `on_wake(trigger=...)` that also fires when you press Enter, and a multiple-choice field via `call.set_task(...)`. Type a level like `50`, `water` or `status` in the terminal to change the moisture.
- [barista.py](./barista.py) - A wake word or Enter key example where an agent takes a coffee order, collecting drink, size and name with multiple-choice and free-text fields via `call.set_task(...)`, then reads back a price worked out in code with `call.read_script(...)`.
