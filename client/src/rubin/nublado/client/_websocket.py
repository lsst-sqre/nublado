"""JupyterLab WebSocket protocol.

See `JupyterLab WebSocket protocol`_ for more details. The
jupyter-server-documents extension only implements
``v1.kernel.websocket.jupyter.org``, so we send all messages in that protocol.
"""

import json
from typing import Any

__all__ = ["decode_websocket_message", "encode_websocket_message"]


def decode_websocket_message(message: str | bytes) -> dict[str, Any]:
    """Decode a message in the JupyterLab WebSocket binary format.

    Only supports ``v1.kernel.websocket.jupyter.org``, which is negotiated by
    the client as a subprotocol.

    Parameters
    ----------
    message
        The message as either Text or Binary. If it is Text, assume it is just
        the full JSON message and simply decode it.

    Returns
    -------
    dict
        The decoded message.

    Raises
    ------
    KeyError
        Raised if the message is malformed.
    ValueError
        Raised if the message is malformed.
    """
    if isinstance(message, str):
        return json.loads(message)

    # Assume the message is in the v1.kernel.websocket.jupyter.org protocol
    # and get the count of offsets.
    offset_count = int.from_bytes(message[:8], byteorder="little")

    # Decode all of the offsets. These will be to the channel, header, parent
    # header, metadata, and content in turn.
    offset = [
        int.from_bytes(message[8 * (i + 1) : 8 * (i + 2)], byteorder="little")
        for i in range(offset_count)
    ]

    # Decode the parts of the message:
    channel = message[offset[0] : offset[1]].decode()
    header = json.loads(message[offset[1] : offset[2]])
    parent_header = json.loads(message[offset[2] : offset[3]])
    metadata = json.loads(message[offset[3] : offset[4]])
    content = json.loads(message[offset[4] : offset[5]])

    # Return the parsed message:
    return {
        "channel": channel,
        "header": header,
        "parent_header": parent_header,
        "metadata": metadata,
        "content": content,
    }


def encode_websocket_message(message: dict[str, Any]) -> bytes:
    """Construct a message in the JupyterLab WebSocket binary format.

    Only supports ``v1.kernel.websocket.jupyter.org``. The
    jupyter-server-documents extension requires that message format.

    Parameters
    ----------
    message
        Message contents to send.

    Returns
    -------
    bytes
        Message encoded in the binary protocol.
    """
    # Each message starts with a sequence of 8-byte little-endian numbers.
    # The first is the count of offsets. Then follows offsets within the
    # message to, in order, the channel name, the header, the parent header,
    # the metadata, and the content. Finally, there is an offset to the end of
    # the message (or, in other words, the total message length).
    #
    # Following that is the channel encoded as a UTF-8 string and then the
    # remaining four elements, all encoded in UTF-8 JSON.

    # Start by encoding the channel name and the data fields.
    channel = message["channel"].encode()
    msg_list = [
        json.dumps(message.get(key, {})).encode()
        for key in ("header", "parent_header", "metadata", "content")
    ]

    # The first offset is the offset of the channel name, which is after the
    # count of offsets, the offset of each field (one more than the length of
    # msg_list since it includes the channel), and the offset to the end of
    # the message.
    offsets = [8 * (1 + 1 + len(msg_list) + 1)]

    # The second offset is to the parent, which is right after the channel.
    offsets.append(len(channel) + offsets[-1])

    # The remaining offsets can be calculated by adding the length of the
    # field in msg_list to the previous offset. The last one will thus be the
    # length of the whole message.
    for msg in msg_list:
        offsets.append(len(msg) + offsets[-1])

    # Encode the count of offsets to go at the start of the message.
    offset_count = len(offsets).to_bytes(8, byteorder="little")
    offsets_bytes = [o.to_bytes(8, byteorder="little") for o in offsets]

    # Join all of the resulting encoded bytes together to form the message.
    return b"".join([offset_count, *offsets_bytes, channel, *msg_list])
