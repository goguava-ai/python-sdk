def chunk_document(document: str, chunk_size: int = 5000, overlap: int = 200) -> list[str]:
    """Split a document into overlapping chunks on paragraph boundaries.

    Paragraphs are grouped until *chunk_size* characters are reached, then
    a new chunk begins. When *overlap* > 0, the last paragraph of each chunk
    is carried over to the next chunk to preserve cross-boundary context.
    """
    paragraphs = [p.strip() for p in document.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        paragraph_length = len(paragraph)
        if current_length + paragraph_length > chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            # Carry the last paragraph into the next chunk for overlap
            if overlap > 0 and current_chunk:
                last = current_chunk[-1]
                current_chunk = [last]
                current_length = len(last)
            else:
                current_chunk = []
                current_length = 0
        current_chunk.append(paragraph)
        current_length += paragraph_length

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks
