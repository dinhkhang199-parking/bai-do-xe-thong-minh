import io
from pathlib import Path
import threading
import time
import numpy as np
from PIL import Image
import pytest
from integrations import local_mb_captcha as local
from integrations import mb_readonly_worker as worker


def image():
    stream=io.BytesIO();Image.new('L',(160,50),255).save(stream,format='PNG');return stream.getvalue()


def probabilities(indices,confidence=.99):
    data=np.full((1,len(indices),43),(1-confidence)/42,dtype=np.float32)
    for i,index in enumerate(indices):data[0,i,index]=confidence
    return data


def test_preprocessing_has_model_layout_and_normalized_pixels():
    value=local.preprocess(image())
    assert value.shape==(1,320,80,1) and value.dtype==np.float32 and value.flags.c_contiguous
    assert np.all(value==1)


def test_ctc_repeats_require_a_blank_separator():
    blank=42;chars=[local.CHARACTERS.index(c)+1 for c in 'AAB234']
    indices=[]
    for char in chars:indices.extend([char,char,blank])
    assert local.decode(probabilities(indices))=='AAB234'


@pytest.mark.parametrize('indices,confidence',[
    ([1,2,3,4,5,6],.4),([0,2,3,4,5,6],.99),([1,2,3],.99),([1,2,3,4,5,6,7],.99),
])
def test_uncertain_unknown_or_wrong_length_requires_manual_entry(indices,confidence):
    with pytest.raises(local.LocalCaptchaError):local.decode(probabilities(indices,confidence))


@pytest.mark.parametrize('value',[b'',b'not-an-image',b'x'*512001],ids=['empty','invalid','oversized'])
def test_invalid_images_are_rejected_without_model_calls(value):
    with pytest.raises(local.LocalCaptchaError):local.preprocess(value)


def test_supplied_model_reads_bank_confirmed_expired_sample():
    pytest.importorskip('onnxruntime')
    sample=Path(__file__).parent/'fixtures/mb-captcha-expired.png'
    assert local.solve(sample.read_bytes())=='GcV5aZ'


def test_local_worker_never_calls_external_solver_and_falls_back_when_uncertain(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'local_captcha_readiness',lambda:{'configured':True})
    external=[];local_calls=[]
    class Bank:
        def __init__(self,callback):self.callback=callback
        def userinfo(self):assert self.callback(image())=='TEST'
        def getBalance(self):return {'acct_list':[{'acctNo':'000123456789','acctNm':'DEMO','ccyCd':'VND'}]}
    def uncertain(data):local_calls.append(1);raise local.LocalCaptchaError('uncertain')
    state=worker.MBState(tmp_path,Bank,lambda *args:external.append(1),uncertain)
    state.connect('local');deadline=time.monotonic()+2
    while state.state!='captcha_required' and time.monotonic()<deadline:time.sleep(.005)
    assert state.state=='captcha_required' and local_calls==[1] and external==[]
    state.solve(state.captcha['id'],'TEST')
    while state.state!='connected' and time.monotonic()<deadline:time.sleep(.005)
    assert state.state=='connected' and external==[]


def test_local_worker_success_requires_no_manual_challenge(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'local_captcha_readiness',lambda:{'configured':True})
    class Bank:
        def __init__(self,callback):self.callback=callback
        def userinfo(self):assert self.callback(image())=='GcV5aZ'
        def getBalance(self):return {'acct_list':[{'acctNo':'000123456789','acctNm':'DEMO','ccyCd':'VND'}]}
    state=worker.MBState(tmp_path,Bank,local_solver=lambda image:'GcV5aZ')
    state.connect('local');deadline=time.monotonic()+2
    while state.state!='connected' and time.monotonic()<deadline:time.sleep(.005)
    assert state.state=='connected' and state.captcha is None
