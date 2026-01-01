#!/usr/bin/env python3
"""Check for invisible Unicode characters in translation output."""

# The text as it appears in the terminal
text = "Cless's father, Miguel: Yeah. How's Mom's cold?"

print("Checking characters in text:")
print(f"Text: {text}")
print(f"Length: {len(text)}")
print()

print("Character breakdown:")
for i, char in enumerate(text):
    code = ord(char)
    name = f"U+{code:04X}"
    if code == 0x27:
        desc = "APOSTROPHE (ASCII)"
    elif code == 0x2019:
        desc = "RIGHT SINGLE QUOTATION MARK"
    elif code == 0x2018:
        desc = "LEFT SINGLE QUOTATION MARK"
    elif code == 0x60:
        desc = "GRAVE ACCENT"
    elif code == 0xB4:
        desc = "ACUTE ACCENT"
    elif code == 0x2032:
        desc = "PRIME"
    elif code == 0x00A0:
        desc = "NO-BREAK SPACE"
    elif code == 0x200B:
        desc = "ZERO WIDTH SPACE"
    elif code == 0x200C:
        desc = "ZERO WIDTH NON-JOINER"
    elif code == 0x200D:
        desc = "ZERO WIDTH JOINER"
    elif code == 0xFEFF:
        desc = "ZERO WIDTH NO-BREAK SPACE (BOM)"
    elif code == 0x2060:
        desc = "WORD JOINER"
    elif code == 32:
        desc = "SPACE"
    elif 32 < code < 127:
        desc = "ASCII"
    else:
        desc = "OTHER"

    if code < 32 or code in [0x00A0, 0x200B, 0x200C, 0x200D, 0xFEFF, 0x2060]:
        print(f"  [{i}] {name} ({desc}) *** INVISIBLE ***")
    elif char in ["'", "'", "'", "`", "´"]:
        print(f"  [{i}] '{char}' {name} ({desc}) *** QUOTE-LIKE ***")
    else:
        print(f"  [{i}] '{char}' {name} ({desc})")
