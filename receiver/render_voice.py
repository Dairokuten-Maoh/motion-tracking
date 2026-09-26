"""Render speech in the isolated VoxCPM environment; no network access is needed.

This CLI owns model loading and reference conditioning. It writes a PCM WAV and
exits, releasing GPU memory. Text arrives on stdin rather than in process listings.
"""
import argparse
from pathlib import Path
import re
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--device', choices=('cuda', 'cpu'), default='cuda')
    args = parser.parse_args()
    text = sys.stdin.read(16001).strip()
    if not text or len(text) > 4000:
        parser.error('Speech text must contain 1 to 4000 characters')
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / '.tools' / 'VoxCPM' / 'src'))
    import numpy as np
    import soundfile as sf
    import torch
    from voxcpm import VoxCPM
    torch.set_num_threads(4)
    started = time.monotonic()
    model = VoxCPM.from_pretrained(
        hf_model_id=str(root / '.tools/tts-model/base'),
        lora_weights_path=str(root / '.tools/tts-model/adapter'),
        load_denoiser=False, optimize=False, device=args.device,
    )
    loaded = time.monotonic()
    # Bound each sentence so the model's audio-token ceiling cannot silently
    # truncate a long reply. Reuse the loaded model across all chunks.
    parts = []
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        while len(sentence) > 240:
            split = sentence.rfind(' ', 0, 241)
            if split < 1: split = 240
            parts.append(sentence[:split]); sentence = sentence[split:].strip()
        if sentence: parts.append(sentence)
    clips = []
    for part in parts:
        clips.append(model.generate(
            text=part, reference_wav_path=str(args.reference.resolve()),
            cfg_value=2.4, inference_timesteps=6, seed=42,
            normalize=False, denoise=False, max_len=600, retry_badcase=False,
        ))
        clips.append(np.zeros(int(model.tts_model.sample_rate * 0.15), dtype=np.float32))
    audio = np.concatenate(clips[:-1])
    if not len(audio) or not np.isfinite(audio).all():
        raise RuntimeError('Voice model returned invalid audio')
    peak = float(np.abs(audio).max())
    if peak < 0.001:
        raise RuntimeError('Voice model returned silence')
    audio = audio * min(0.9 / peak, 3.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(args.output), audio, model.tts_model.sample_rate, subtype='PCM_16')
    print(f'load_seconds={loaded-started:.2f} synthesis_seconds={time.monotonic()-loaded:.2f} '
          f'audio_seconds={len(audio)/model.tts_model.sample_rate:.2f}', flush=True)


if __name__ == '__main__':
    main()
