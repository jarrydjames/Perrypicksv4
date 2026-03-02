from __future__ import annotations

from reptar.model import ReptarModel


def main() -> int:
    m = ReptarModel()
    m.load()

    # Minimal smoke: zero-fill feature vector.
    feats = {f: 0.0 for f in m.features}
    total, margin = m.predict(feats)
    print("ok")
    print("n_features", len(m.features))
    print("pred_total", total)
    print("pred_margin", margin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
