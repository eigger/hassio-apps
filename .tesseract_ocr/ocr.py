from PIL import Image
import pytesseract
import cv2
import numpy as np
import os

def process_image(image_bytes, rotate=0, roi=None):
    pil_image = Image.open(image_bytes)

    if rotate:
        pil_image = pil_image.rotate(-float(rotate), expand=True)

    if roi:
        roi_values = tuple(map(int, roi.split(',')))
        pil_image = pil_image.crop(roi_values)

    # PIL 이미지를 OpenCV 형식으로 변환
    open_cv_image = np.array(pil_image) 
    open_cv_image = open_cv_image[:, :, ::-1].copy()  # RGB to BGR

    # 이미지 전처리
    gray_image = cv2.cvtColor(open_cv_image, cv2.COLOR_BGR2GRAY)
    resized_gray = cv2.resize(gray_image, None, fx=1, fy=1, interpolation=cv2.INTER_LANCZOS4)
    binary_image = cv2.adaptiveThreshold(resized_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)

    # 잡음제거
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
    binary_image = cv2.morphologyEx(binary_image, cv2.MORPH_OPEN, kernel, iterations=3)
    binary_image = cv2.morphologyEx(binary_image, cv2.MORPH_CLOSE, kernel, iterations=3)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    binary_image = cv2.morphologyEx(binary_image, cv2.MORPH_OPEN, kernel, iterations=1)
    binary_image = cv2.morphologyEx(binary_image, cv2.MORPH_CLOSE, kernel, iterations=1)

    # 블러 처리
    binary_image = cv2.GaussianBlur(binary_image, (5, 5), 0)
    binary_image = cv2.medianBlur(binary_image, 3)

    # 윤곽선 강조
    edges = cv2.Canny(binary_image, 30, 70)
    binary_image = cv2.bitwise_not(binary_image)
    binary_image = cv2.bitwise_or(binary_image, edges)
    binary_image = cv2.bitwise_not(binary_image)

    return open_cv_image, binary_image

def find_ocr_data(mat_image):
    return pytesseract.image_to_data(Image.fromarray(mat_image), output_type=pytesseract.Output.DICT)

def draw_text(open_cv_image, ocr_data):
    for i in range(len(ocr_data['text'])):
        if int(ocr_data['conf'][i]) > 60:
            x = int(ocr_data['left'][i])
            y = int(ocr_data['top'][i])
            w = int(ocr_data['width'][i])
            h = int(ocr_data['height'][i])
            cv2.rectangle(open_cv_image, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.putText(open_cv_image, ocr_data['text'][i], (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

def find_text(ocr_data):
    extracted_text = []
    for i in range(len(ocr_data['text'])):
        if int(ocr_data['conf'][i]) > 60:
            extracted_text.append(ocr_data['text'][i])
    return extracted_text

def save_images(image, file):
    save_dir = '/config/tesseract_ocr/result'
    result_path = os.path.join(save_dir, file)
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
    cv2.imwrite(result_path, image)

if __name__ == "__main__":
    image_path = 'C:/Users/eigger/Downloads/cam_snapshot (7).jpg'
    open_cv_image, binary_image = process_image(image_path)
    ocr_data = find_ocr_data(binary_image)
    extracted_text = find_text(ocr_data)
    draw_text(open_cv_image, ocr_data)
    cv2.imshow("bin", binary_image)
    cv2.imshow("org", open_cv_image)

    print("OCR 결과 텍스트:")
    print("\n".join(extracted_text))
    cv2.waitKey(0)
    cv2.destroyAllWindows()