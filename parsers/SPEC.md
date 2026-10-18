# Synthetic parser specification

This first parser milestone uses a deliberately small synthetic format for safe, repeatable testing. It is not an Intel firmware descriptor implementation.

## Header

- Bytes 0–3: ASCII magic `OMES`
- Bytes 4–7: little-endian unsigned 32-bit region count

## Region entries

Each entry is 16 bytes:

- Bytes 0–3: ASCII region name
- Bytes 4–7: little-endian unsigned 32-bit offset
- Bytes 8–11: little-endian unsigned 32-bit size
- Bytes 12–15: reserved bytes; must be zero

The parser reports file size, SHA-256, regions, region hashes, and structural warnings. It never modifies the input image.

Exit codes:

- `0`: successful inspection
- `1`: malformed image
- `2`: missing or unreadable file

