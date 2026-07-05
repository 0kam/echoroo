# Machine-Learning Model Licenses

This document states factual information about the licensing of the
machine-learning model weights that Echoroo can use. **It is not legal advice.**
If you deploy Echoroo, you are responsible for verifying the current terms of
each model's weights against their upstream sources and for your own compliance.

## Summary

- **Echoroo's own source code** is licensed under the **GNU GPL v3**
  (see [LICENSE](LICENSE)).
- **Model weights are NOT covered by Echoroo's repository license.** They are
  separate works with their own licenses, obtained at runtime.
- Echoroo does **not** vendor or embed any model weights in this repository.
  Both BirdNET and Perch weights are downloaded automatically at runtime by the
  [`birdnet`](https://pypi.org/project/birdnet/) Python package (a declared
  backend dependency in `apps/api/pyproject.toml`) on first use.

## BirdNET (v2.4)

Echoroo loads BirdNET via the `birdnet` PyPI library
(`apps/api/echoroo/ml/birdnet_wrapper.py`, `BIRDNET_VERSION = "2.4"`). The
library downloads the model on first use; the weights are not stored in this
repository.

Facts about upstream BirdNET licensing (verify against the BirdNET project):

- The **BirdNET model weights** distributed by the BirdNET team (K. Lisa Yang
  Center for Conservation Bioacoustics, Cornell Lab of Ornithology, and
  collaborators) are released under
  **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 (CC BY-NC-SA 4.0)**
  — i.e. **non-commercial** use only.
- The **source code** in the upstream `BirdNET-Analyzer` repository is released
  under the **MIT License**.

These are two different licenses covering two different things (weights vs.
code). Using the BirdNET weights subjects a deployment to the
**non-commercial** terms of CC BY-NC-SA 4.0.

## Perch (Perch V2)

Echoroo loads Perch via the same `birdnet` library
(`apps/api/echoroo/ml/perch/loader.py` calls `birdnet.load_perch_v2()`, which
"downloads the ProtoBuf model automatically on first use"). Perch is a
general-purpose bioacoustic audio-embedding model developed by **Google
Research**; the weights are not stored in this repository.

Facts about upstream Perch licensing (verify against the Perch project /
model card):

- Google's Perch project source code is typically released under the
  **Apache License 2.0**. The model weights are distributed via Google's model
  hosting (e.g. Kaggle Models / model card); confirm the specific weights'
  license and usage terms on the upstream model card before relying on them.

## What this means for deployments

- If you run Echoroo with **BirdNET weights**, your use is subject to the
  weights' license (**CC BY-NC-SA 4.0 — non-commercial**), independently of
  Echoroo's GPL-3.0 code license.
- Perch weights carry their own upstream terms; check the current model card.
- Echoroo's GPL-3.0 license applies to Echoroo's code only and does **not**
  relicense, sublicense, or grant any rights over third-party model weights.

For the licensing of Echoroo's software dependencies (as opposed to model
weights), see [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
