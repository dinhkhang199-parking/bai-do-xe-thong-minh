# Local MB CAPTCHA model

Provided by the user from `bank_captcha_solver-master/mbbank/mbbank.onnx` on 2026-11-02.
The supplied repository README states MIT licensing. Its source uses ONNX Runtime inference and a CTC decoder.

The ITS adapter loads only the MB model on CPU (one inference thread). It does not import the supplied Flask app, open a public port, install TensorFlow, or send images to another service.

Input: float32 `[batch,320,80,1]`, grayscale normalized to 0–1, bilinear resize and width/height transpose. Output: CTC probabilities with 41 allowed characters, one unknown token and one blank token.

Low-confidence, unknown-character or non-six-character results require manual entry. The worker does not automatically log in on startup. A rejected automatic CAPTCHA has at most one manual fallback; other bank errors do not trigger repeated logins.

Optional worker dependencies: `onnxruntime>=1.24,<2`, `numpy>=2.3,<3`, Pillow.
