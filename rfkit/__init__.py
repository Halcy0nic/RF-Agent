"""rfkit: small NumPy toolkit for generating, reading and analysing IQ.

Modules
    iq    read/write CS8, CU8, CS16, CF32, WAV (SDR++), SigMF
    bits  bytes<->bits, Manchester, NRZI, differential, PN9 whitening, CRCs, packet framing, Morse
    mod   modulators: tone, AM/FM/SSB, Morse, OOK/ASK, FSK/GFSK/MSK, PSK/QAM (RRC), chirps/CSS, DSSS, OFDM,
          waterfall images, AWGN and impairments
    dsp   receivers: PSD, spectrogram, carrier search, channelizer, envelope/FM discriminator, bursts,
          symbol-rate estimation, slicing, Costas loop, SNR
    plot  PNG plots (PSD, waterfall, overview, constellation, eye) — headless

Add the repo root to sys.path (or `pip install -e .`) and `from rfkit import iq, bits, mod, dsp`.
"""
from . import bits, dsp, iq, mod  # noqa: F401

__all__ = ["bits", "dsp", "iq", "mod"]
__version__ = "0.1.0"
