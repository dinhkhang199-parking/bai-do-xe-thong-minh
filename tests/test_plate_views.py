from types import SimpleNamespace

from PIL import Image,ImageDraw
import pytest

from backend import plate_views,openai_vision_adapter as adapter


def test_single_plate_provides_original_crop_and_contrast_view(tmp_path):
    path=tmp_path/"test.png"
    image=Image.new("RGB",(240,150),"#c7ddeb");ImageDraw.Draw(image).text((30,45),"59-B1 123.45",fill="black");image.save(path)
    views=plate_views.crop_views(path,finder=lambda image:[(20,30,180,100)])
    assert len(views)==2
    assert all(view.mode=="RGB" and max(view.size)<=1200 for _,view in views)
    assert views[0][1].size==views[1][1].size


@pytest.mark.parametrize("boxes",[[],[(10,10,100,50),(130,10,230,50)],[(10,10,12,13)]])
def test_ambiguous_or_too_small_regions_do_not_force_a_crop(tmp_path,boxes):
    path=tmp_path/"test.png";Image.new("RGB",(240,150),"white").save(path)
    assert plate_views.crop_views(path,finder=lambda _:boxes)==[]


def test_detector_failure_preserves_full_frame_fallback(tmp_path):
    path=tmp_path/"test.png";Image.new("RGB",(240,150),"white").save(path)
    def broken(_):raise RuntimeError("fixture detector unavailable")
    assert plate_views.crop_views(path,finder=broken)==[]


def test_phone_exif_orientation_is_applied_before_detector(tmp_path):
    path=tmp_path/"phone.jpg";image=Image.new("RGB",(120,80),"white");exif=image.getexif();exif[274]=6;image.save(path,exif=exif)
    seen=[]
    plate_views.crop_views(path,finder=lambda image:seen.append(image.size) or [])
    assert seen==[(80,120)]


def test_sol61_request_uses_high_detail_for_all_views_and_high_reasoning():
    calls=[]
    client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kw:calls.append(kw) or SimpleNamespace(status="completed",output_text="{}")))
    adapter._responses_request(client,[("original","AAA"),("crop","BBB"),("contrast","CCC")],
        SimpleNamespace(model="cx/gpt-6.1-sol",timeout=60))
    request=calls[0]
    images=[part for part in request["input"][0]["content"] if part["type"]=="input_image"]
    assert len(images)==3 and all(part["detail"]=="high" for part in images)
    assert request["model"]=="cx/gpt-6.1-sol" and request["reasoning"]=={"effort":"high"}
    assert request["store"] is False


def test_other_models_keep_their_own_reasoning_defaults():
    calls=[]
    client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kw:calls.append(kw) or SimpleNamespace(status="completed",output_text="{}")))
    adapter._responses_request(client,"AAA",SimpleNamespace(model="fixture-model",timeout=1))
    assert "reasoning" not in calls[0]
