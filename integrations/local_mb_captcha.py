"""Image-only MB CAPTCHA inference using the user's local ONNX model."""
from __future__ import annotations
import importlib.util
import io
from pathlib import Path
import threading

from PIL import Image

MODEL_PATH=Path(__file__).resolve().parents[1]/'models/mb-captcha.onnx'
CHARACTERS='23456789ABCDEGHKMNPQUVYZabcdeghkmnpqtuvyz'
_session=None
_lock=threading.Lock()


class LocalCaptchaError(RuntimeError):
    pass


def readiness():
    return {'provider':'Local ONNX','configured':MODEL_PATH.is_file() and
        importlib.util.find_spec('onnxruntime') is not None and importlib.util.find_spec('numpy') is not None,
        'external_service':False}


def _get_session():
    global _session
    with _lock:
        if _session is None:
            import onnxruntime as ort
            options=ort.SessionOptions();options.intra_op_num_threads=1;options.inter_op_num_threads=1
            options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
            session=ort.InferenceSession(str(MODEL_PATH),sess_options=options,providers=['CPUExecutionProvider'])
            inputs=session.get_inputs()
            if len(inputs)!=1 or inputs[0].shape[1:]!=[320,80,1] or inputs[0].type!='tensor(float)':
                raise LocalCaptchaError('Mô hình CAPTCHA MB không đúng định dạng.')
            _session=session
        return _session


def preprocess(image):
    import numpy as np
    if not isinstance(image,bytes) or not image or len(image)>512000:
        raise LocalCaptchaError('Ảnh CAPTCHA không hợp lệ.')
    try:
        with Image.open(io.BytesIO(image)) as opened:
            if opened.width*opened.height>1000000:raise LocalCaptchaError('Ảnh CAPTCHA quá lớn.')
            gray=np.asarray(opened.convert('L'),dtype=np.float32)/255.0
        # Bilinear interpolation with half-pixel centers, matching tf.image.resize.
        height,width=gray.shape
        xs=np.maximum((np.arange(320,dtype=np.float32)+.5)*(width/320)-.5,0)
        ys=np.maximum((np.arange(80,dtype=np.float32)+.5)*(height/80)-.5,0)
        x0=xs.astype(np.int32);y0=ys.astype(np.int32)
        x1=np.minimum(x0+1,width-1);y1=np.minimum(y0+1,height-1)
        wx=xs-x0;wy=ys-y0
        top=gray[y0[:,None],x0]*(1-wx)+gray[y0[:,None],x1]*wx
        bottom=gray[y1[:,None],x0]*(1-wx)+gray[y1[:,None],x1]*wx
        resized=top*(1-wy[:,None])+bottom*wy[:,None]
        return np.ascontiguousarray(resized.T[None,:,:,None],dtype=np.float32)
    except (OSError,ValueError,Image.DecompressionBombError):
        raise LocalCaptchaError('Không đọc được ảnh CAPTCHA.') from None


def decode(prediction):
    import numpy as np
    values=np.asarray(prediction)
    if values.ndim!=3 or values.shape[0]!=1 or values.shape[-1]!=len(CHARACTERS)+2 or not np.isfinite(values).all():
        raise LocalCaptchaError('Kết quả mô hình CAPTCHA không hợp lệ.')
    if np.min(values)<0 or np.max(values)>1 or not np.allclose(values.sum(axis=-1),1,atol=.02):
        raise LocalCaptchaError('Độ tin cậy mô hình CAPTCHA không hợp lệ.')
    blank=values.shape[-1]-1;previous=-1;chars=[];scores=[]
    for index,row in zip(values[0].argmax(axis=-1),values[0]):
        index=int(index)
        if index==0:raise LocalCaptchaError('Có ký tự CAPTCHA chưa nhận rõ.')
        if index!=previous and index!=blank:
            chars.append(CHARACTERS[index-1]);scores.append(float(row[index]))
        elif index==previous and index!=blank:
            scores[-1]=max(scores[-1],float(row[index]))
        previous=index
    if len(chars)!=6 or min(scores,default=0)<.55 or sum(scores)/max(len(scores),1)<.8:
        raise LocalCaptchaError('CAPTCHA chưa đủ rõ; cần nhập tay.')
    return ''.join(chars)


def solve(image,session=None):
    try:
        tensor=preprocess(image);session=session or _get_session()
        prediction=session.run(None,{session.get_inputs()[0].name:tensor})[0]
        return decode(prediction)
    except LocalCaptchaError:raise
    except Exception:
        raise LocalCaptchaError('Bộ giải CAPTCHA cục bộ chưa sẵn sàng; cần nhập tay.') from None
