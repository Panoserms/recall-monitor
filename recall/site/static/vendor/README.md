# Third-party files served by the site

Copied unchanged from the npm packages below on 17 Nov 2026. Served from this site so that no visitor request goes
elsewhere. Loaded only when a visitor adds a PDF (pdf.js) or a picture (Tesseract.js).

| Folder | Package | Version | Licence | Visitor download |
|---|---|---|---|---|
| `pdfjs/` | `pdfjs-dist` (legacy build, for older Safari) | 4.10.38 | Apache-2.0 (`pdfjs/LICENSE`) | about 1.8 MB, only for a PDF |
| `tesseract/` | `tesseract.js` | 6.0.1 | Apache-2.0 (`tesseract/LICENSE.md`) | 0.2 MB |
| `tesseract/core/` | `tesseract.js-core`, LSTM builds with and without SIMD | 6.1.2 | Apache-2.0 (`tesseract/core/LICENSE`) | about 4 MB (one of the two) |
| `tesseract/lang/` | `@tesseract.js-data/deu`, `4.0.0_best_int` model | 1.0.0 | Apache-2.0 (Tesseract models) | 1.3 MB |

SHA-256:
```
0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594  ./pdfjs/LICENSE
44ec6f011027ee77791386b66c14876a5fc29e20bf0433c07c6726fff7212b72  ./pdfjs/pdf.min.mjs
bd88805178a26c729db8c0107a5b630cb900ec070f4d8c7529a3e45530afd41d  ./pdfjs/pdf.worker.min.mjs
c6596eb7be8581c18be736c846fb9173b69eccf6ef94c5135893ec56bd92ba08  ./tesseract/core/LICENSE
775a35df6f2ae100e02609443e6bd5cafcd07983dd6175454ca4a432a7730687  ./tesseract/core/tesseract-core-lstm.wasm.js
9d7c43fb206dc9f48475228b46bf35f888fa9e6259da2e67d5a75c77049f2dc7  ./tesseract/core/tesseract-core-simd-lstm.wasm.js
306c4280d0cbed46fbff727486bd43b92730181bae80f56941a091f363bdf28b  ./tesseract/lang/deu.traineddata.gz
b40930bbcf80744c86c46a12bc9da056641d722716c378f5659b9e555ef833e1  ./tesseract/LICENSE.md
10fff78484067759c43028a02a72d76d0b90eb17302bb23b58a9ec5410bc928b  ./tesseract/tesseract.min.js
38645599043239c0eb6db08a6504a92dcdc292200535f3e9339cd77c4443b842  ./tesseract/worker.min.js
```
