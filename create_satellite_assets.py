import os

# Create placeholder satellite PNG assets for zero-fail fallback
os.makedirs("assets/satellite_chokepoints", exist_ok=True)

# Minimal 1x1 pixel PNG (1x1 black pixel) for each chokepoint
# Base64 encoded 1x1 black PNG: iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==
# We'll create simple text files as placeholders since actual PNG creation requires PIL
for name in ["hormuz", "bab_el_mandeb", "malacca"]:
    path = f"assets/satellite_chokepoints/{name}.png"
    with open(path, "wb") as f:
        # Write a minimal valid PNG header (1x1 black pixel)
        f.write(bytes([
            0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
            0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk length
            0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # width=1, height=1
            0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x0B, 0x13,  # bit depth=8, color type=2, compression=0, filter=0, interlace=0
            0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41, 0x74,  # IDAT chunk length
            0x08, 0xD7, 0x63, 0x60, 0x00, 0x00, 0x00, 0x02,  # compressed data (2 bytes)
            0x00, 0x01, 0xE5, 0x00, 0x00, 0x00, 0x00, 0x49,  # IEND chunk
            0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82
        ]))
    print(f"Created placeholder {path}")
