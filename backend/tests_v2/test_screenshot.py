"""Screenshot intake never invents values when no vision model is available."""
import io


def test_upload_without_vision_model_is_honest(client, victim_headers):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = client.post("/api/portal/upload-screenshot", files={"file": ("pay.png", io.BytesIO(png), "image/png")},
                    headers=victim_headers)
    assert r.status_code == 200
    ocr = r.json()["ocr_data"]
    assert ocr["provider"] == "fallback" and ocr["is_uncertain"] is True
    assert ocr["extracted_fields"]["amount"] is None and ocr["extracted_fields"]["transaction_id"] is None
