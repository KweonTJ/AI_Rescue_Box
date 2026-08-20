"""Apply the minimal thotro DW1000 v0.9 ESP32 SPI compatibility guard.

PlatformIO's POST extra-script phase runs after dependent libraries have been
resolved but before SCons executes their compile actions.  The upstream v0.9
source calls SPI.usingInterrupt(), an AVR-style API that ESP32 SPIClass does
not provide.  Keep the call for supported non-ESP targets and skip it only when
ESP32 is defined.  No project radio/framing code is modified.
"""

from pathlib import Path

Import("env")  # type: ignore[name-defined]  # provided by PlatformIO/SCons

if env.IsIntegrationDump():  # type: ignore[name-defined]
    Return()  # type: ignore[name-defined]

libdeps = Path(env.subst("$PROJECT_LIBDEPS_DIR")) / env.subst("$PIOENV")  # type: ignore[name-defined]
candidates = sorted(libdeps.glob("*/src/DW1000.cpp"))
if len(candidates) != 1:
    raise RuntimeError(
        "expected exactly one thotro DW1000.cpp in PlatformIO libdeps, found "
        f"{len(candidates)} under {libdeps}"
    )

source = candidates[0]
text = source.read_text(encoding="utf-8")
legacy = (
    "#ifndef ESP8266\n"
    "\tSPI.usingInterrupt(digitalPinToInterrupt(irq)); // not every board support this, e.g. ESP8266\n"
    "#endif\n"
)
patched = (
    "#if !defined(ESP8266) && !defined(ESP32)\n"
    "\tSPI.usingInterrupt(digitalPinToInterrupt(irq)); // not every board support this, e.g. ESP8266/ESP32\n"
    "#endif\n"
)
if patched in text:
    print(f"DW1000 ESP32 compatibility guard already patched: {source}")
elif legacy in text:
    source.write_text(text.replace(legacy, patched, 1), encoding="utf-8")
    print(f"Patched DW1000 v0.9 SPI interrupt guard for ESP32: {source}")
else:
    raise RuntimeError(
        "thotro DW1000.cpp no longer matches the reviewed v0.9 SPI guard; "
        "refusing an unverified dependency patch"
    )
