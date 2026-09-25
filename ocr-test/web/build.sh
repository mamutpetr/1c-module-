#!/usr/bin/env bash
# Збирає папку dist/ зі сторінкою та файлами рушія Tesseract.js (усе локально, без CDN).
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
(cd "$tmp" && npm pack -s tesseract.js@7.0.0 tesseract.js-core@7.0.0 \
  @tesseract.js-data/ukr@1.0.0 @tesseract.js-data/rus@1.0.0 @tesseract.js-data/eng@1.0.0 >/dev/null \
  && for f in *.tgz; do mkdir "${f%.tgz}" && tar xzf "$f" -C "${f%.tgz}"; done)

rm -rf dist && mkdir -p dist/core dist/lang dist/samples
cp ocr.html ocr-worker.js dist/
cp "$tmp"/tesseract.js-7.0.0/package/dist/{tesseract.min.js,worker.min.js} dist/
cp "$tmp"/tesseract.js-core-7.0.0/package/tesseract-core-{relaxedsimd-lstm,simd-lstm,lstm}.wasm.js dist/core/
for l in ukr rus eng; do
  base64 -w0 "$tmp/tesseract.js-data-$l-1.0.0/package/4.0.0_best_int/$l.traineddata.gz" > "dist/lang/$l.traineddata.gz.b64.txt"
done
cp ../samples/*.png dist/samples/
echo "Готово: $(du -sh dist | cut -f1). Локально: python3 -m http.server -d dist, далі /ocr.html"
