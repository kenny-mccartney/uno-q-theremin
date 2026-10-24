# SPDX-FileCopyrightText: Copyright (C) Arduino s.r.l. and/or its affiliated companies
#
# SPDX-License-Identifier: MPL-2.0

import math
import threading

import alsaaudio
import numpy as np

from arduino.app_bricks.web_ui import WebUI
from arduino.app_utils import App, Logger

logger = Logger("theremin")

# The Wave Generator brick's Speaker peripheral only detects USB audio
# devices, so it can't see the Media Carrier's onboard headphone jack
# (ALSA card 0, "Arduino-Imola-HPH-LOUT", native 8000 Hz mono). We talk to
# ALSA directly instead, via the "default" PCM so its plug layer handles
# the rate conversion for us.
SAMPLE_RATE = 44100
CHUNK_SAMPLES = 512
ATTACK = 0.01
RELEASE = 0.03
GLIDE = 0.02

_lock = threading.Lock()
_target_freq = 440.0
_target_amp = 0.0
_power_on = False
_volume = 100


def _freq_from_x(x):
    return 20.0 * ((SAMPLE_RATE / 2.0 / 20.0) ** x)


def _audio_loop():
    device = alsaaudio.PCM(
        type=alsaaudio.PCM_PLAYBACK,
        mode=alsaaudio.PCM_NORMAL,
        device="default",
        channels=1,
        rate=SAMPLE_RATE,
        format=alsaaudio.PCM_FORMAT_S16_LE,
        periodsize=CHUNK_SAMPLES,
    )

    glide_coeff = math.exp(-1.0 / (GLIDE * SAMPLE_RATE))
    attack_coeff = math.exp(-1.0 / (ATTACK * SAMPLE_RATE))
    release_coeff = math.exp(-1.0 / (RELEASE * SAMPLE_RATE))

    phase = 0.0
    current_freq = _target_freq
    current_amp = 0.0
    samples = np.empty(CHUNK_SAMPLES, dtype=np.int16)

    while True:
        with _lock:
            target_freq = _target_freq
            target_amp = _target_amp if _power_on else 0.0
            volume = _volume / 100.0

        for i in range(CHUNK_SAMPLES):
            current_freq += (target_freq - current_freq) * (1.0 - glide_coeff)
            coeff = attack_coeff if target_amp > current_amp else release_coeff
            current_amp += (target_amp - current_amp) * (1.0 - coeff)

            phase += 2 * math.pi * current_freq / SAMPLE_RATE
            if phase > 2 * math.pi:
                phase -= 2 * math.pi

            sample = max(-1.0, min(1.0, math.sin(phase) * current_amp * volume))
            samples[i] = int(sample * 32767)

        device.write(samples.tobytes())


_audio_thread = threading.Thread(target=_audio_loop, daemon=True)
_audio_thread.start()


ui = WebUI()


def on_connect(sid, data=None):
    ui.send_message("theremin:state", {"freq": _target_freq, "amp": _target_amp})
    ui.send_message("theremin:volume", {"volume": _volume})


def on_move(sid, data=None):
    global _target_freq, _target_amp
    d = data or {}
    x = float(d.get("x", 0.0))
    y = float(d.get("y", 1.0))
    freq = d.get("freq")
    freq = float(freq) if freq is not None else _freq_from_x(x)
    amp = max(0.0, min(1.0, 1.0 - float(y)))
    logger.debug(f"on_move: x={x:.3f}, y={y:.3f} -> freq={freq:.1f}Hz, amp={amp:.3f}")
    with _lock:
        _target_freq = freq
        _target_amp = amp
    ui.send_message("theremin:state", {"freq": freq, "amp": amp}, room=sid)


def on_power(sid, data=None):
    global _power_on
    d = data or {}
    with _lock:
        _power_on = bool(d.get("on", False))


def on_set_volume(sid, data=None):
    global _volume
    d = data or {}
    volume = max(0, min(100, int(d.get("volume", 100))))
    with _lock:
        _volume = volume
    ui.send_message("theremin:volume", {"volume": volume})


ui.on_connect(on_connect)
ui.on_message("theremin:move", on_move)
ui.on_message("theremin:power", on_power)
ui.on_message("theremin:set_volume", on_set_volume)

App.run()
