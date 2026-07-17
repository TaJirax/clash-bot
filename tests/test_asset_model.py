import cv2
import numpy as np

from clashbot.asset_model import AssetRetrievalModel, feature


def test_retrieval_model_uses_all_rows_and_returns_nearest_label():
    first = np.zeros((32, 32, 4), dtype=np.uint8)
    first[:, :, 2] = 255
    first[:, :, 3] = 255
    second = np.zeros((32, 32, 4), dtype=np.uint8)
    second[:, :, 1] = 255
    second[:, :, 3] = 255
    matrix = np.vstack([feature(first), feature(second)])
    model = AssetRetrievalModel(matrix, ("red", "green"), ("a", "b"))

    prediction = model.predict(first, k=2)

    assert len(prediction) == 2
    assert prediction[0].label == "red"
    assert prediction[0].similarity >= prediction[1].similarity


def test_feature_accepts_png_decoded_with_alpha():
    image = np.zeros((16, 16, 4), dtype=np.uint8)
    image[3:12, 4:10] = (20, 30, 40, 255)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    decoded = cv2.imdecode(encoded, cv2.IMREAD_UNCHANGED)
    assert feature(decoded).ndim == 1
