"""OOK data packet: carrier on = 1, off = 0. Framed with preamble, sync word, length and CRC-16."""
import numpy as np

from sdr_helpers import (SAMPLE_RATE, bytes_to_bits, packet, pad_silence, raised_cosine_edges, save_cs8,
                         shift_to_offset)

BIT_RATE = 1_000                                    # 1 kbit/s -> 1 ms per bit, 2000 samples per bit
bits = bytes_to_bits(packet(b"PING 42"))
bits = np.concatenate([bits, [0]])                  # trailing 0 so the last bit's falling edge is clean
envelope = np.repeat(bits, SAMPLE_RATE // BIT_RATE).astype(np.float32)
envelope = raised_cosine_edges(envelope, 0.1 / BIT_RATE)   # edges = 10 % of a bit
burst = shift_to_offset(envelope.astype(np.complex64))
gap = np.zeros(int(0.2 * SAMPLE_RATE), dtype=np.complex64)
save_cs8(pad_silence(np.concatenate([burst, gap, burst, gap, burst])), "ook.cs8")   # 3 copies
