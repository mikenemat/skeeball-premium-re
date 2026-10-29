"""JLC04161H-7628 board stackup for SBC-1 (adversarial review L2 / F09, q5 2026-10-27; DECISIONS #7): 35 um outer /
17.5 um inner copper, 7628 prepreg 0.2104 mm (er 4.4) each side of a 1.065 mm core (er 4.6) -> 1.61 mm. Written into the
board's (setup) by pcb_build.py (and onto a routed board by apply()), so the Gerber job file, DRC and any impedance
estimate use the stack JLC builds."""
STACKUP = """\t\t(stackup
\t\t\t(layer "F.SilkS" (type "Top Silk Screen"))
\t\t\t(layer "F.Paste" (type "Top Solder Paste"))
\t\t\t(layer "F.Mask" (type "Top Solder Mask") (color "Green") (thickness 0.01))
\t\t\t(layer "F.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "dielectric 1" (type "prepreg") (color "FR4 natural") (thickness 0.2104) (material "7628") (epsilon_r 4.4) (loss_tangent 0.02))
\t\t\t(layer "In1.Cu" (type "copper") (thickness 0.0175))
\t\t\t(layer "dielectric 2" (type "core") (color "FR4 natural") (thickness 1.065) (material "FR4") (epsilon_r 4.6) (loss_tangent 0.02))
\t\t\t(layer "In2.Cu" (type "copper") (thickness 0.0175))
\t\t\t(layer "dielectric 3" (type "prepreg") (color "FR4 natural") (thickness 0.2104) (material "7628") (epsilon_r 4.4) (loss_tangent 0.02))
\t\t\t(layer "B.Cu" (type "copper") (thickness 0.035))
\t\t\t(layer "B.Mask" (type "Bottom Solder Mask") (color "Green") (thickness 0.01))
\t\t\t(layer "B.Paste" (type "Bottom Solder Paste"))
\t\t\t(layer "B.SilkS" (type "Bottom Silk Screen"))
\t\t\t(copper_finish "ENIG")
\t\t\t(dielectric_constraints no)
\t\t)
"""



def apply(text):
    """board text with STACKUP as the first item of (setup) (an existing (stackup ...) block is replaced)"""
    import re
    crlf = "\r\n" in text
    text = text.replace("\r\n", "\n")
    text = re.sub(r"\t\t\(stackup\n.*?\n\t\t\)\n", "", text, count=1, flags=re.S)
    i = text.index("\t(setup\n") + len("\t(setup\n")
    text = text[:i] + STACKUP + text[i:]
    return text.replace("\n", "\r\n") if crlf else text


if __name__ == "__main__":
    import sys
    p = sys.argv[1]
    s = open(p, encoding="utf-8", newline="").read()
    out = apply(s)                                    # (never open the board for writing before the new text exists)
    open(p, "w", encoding="utf-8", newline="").write(out)
    print("stackup: JLC04161H-7628 ->", p)
