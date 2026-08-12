from flask import Flask, request, jsonify
import io
import requests
import ocr
import datetime

app = Flask(__name__)

@app.route("/ocr", methods=["POST"])
def process_ocr():
    data = {"success": False, "error": ""}

    image_url = request.json.get('image_url')
    rotate = request.json.get('rotate', 0)
    roi = request.json.get('roi')

    if not image_url:
        data['error'] = '이미지 URL이 제공되지 않았습니다.'
        return jsonify(data), 400

    try:
        response = requests.get(image_url)
        response.raise_for_status()
        image_bytes = io.BytesIO(response.content)
        open_cv_image, binary_image = ocr.process_image(image_bytes, rotate, roi)
        ocr_data = ocr.find_ocr_data(binary_image)
        extracted_text = ocr.find_text(ocr_data)
        ocr.draw_text(open_cv_image, ocr_data)

        current_datetime = datetime.datetime.now().strftime('%Y%m%d%H%M%S')
        ocr.save_images(open_cv_image, 'overlay_image.jpg')
        ocr.save_images(binary_image, 'binary_image.jpg')
        # ocr.save_images(open_cv_image, f'overlay_image_{current_datetime}.jpg')
        # ocr.save_images(binary_image, f'binary_image_{current_datetime}.jpg')

        data['text'] = "\n".join(extracted_text)
        data['success'] = True
    except requests.RequestException as e:
        data['error'] = f'이미지 다운로드 실패: {str(e)}'
        return jsonify(data), 500
    except IOError:
        data['error'] = '이미지 파일 처리 중 오류가 발생했습니다.'
        return jsonify(data), 500
    except Exception as e:
        data['error'] = str(e)
        return jsonify(data), 500

    return jsonify(data)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5080, debug=True)
