# Generated narration assets

The two FLAC files are deterministic source narration for the home promotion film.
They are kept outside the public static tree and are consumed by
`tools/generate_home_promo.py` when the localized MP4 files are rebuilt.

- `home-promo-narration-ro.flac`: Piper `ro_RO-mihai-medium`, voice dataset CC0,
  generated locally with Piper TTS 1.8.0. Model SHA-256:
  `e0608bbbd53c80267c09ece681b09f5199f54e792356684c8073738e5f15d29f`.
- `home-promo-narration-en.flac`: Piper `en_US-joe-medium`, voice dataset CC0,
  generated locally with Piper TTS 1.8.0.

Model catalogue: https://huggingface.co/rhasspy/piper-voices

The model binaries are development inputs and are not distributed with the app.
The generated narration contains only the promotional scripts stored alongside the
film generator and no cloned or user-supplied voice.
