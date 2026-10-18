# Runtime models

Synthetic boot phases, services, bounded storage, and a software research
console live here. These models remain separate from the real-byte execution
path.

`real_image_attempt.py` verifies and classifies a preserved ME image, decodes
ME11 Huffman modules with the public dictionary, builds bounded mappings, and
invokes the real-byte backend from the image's process-attributes entry. The
default path still requires cryptographic admission evidence. An explicit
`--allow-emulation-auth-bypass` experiment bypasses only that local admission
gate; it does not claim a signature was accepted or change physical hardware.
Missing ROM/library state, unsupported instructions, invalid memory, timeouts,
and SPI writes remain visible hard stops; none is converted into synthetic
success.
