# hassio-apps : Tesseract OCR
```
sensor:
  - platform: rest
    name: OCR Text Extraction
    resource: http://<your_flask_server_ip>:5080/ocr
    method: POST
    headers:
      Content-Type: application/json
    payload: >-
      {
        "image_url": "http://url_to_your_image.jpg",
        "roi": "x,y,width,height",
        "rotate": "90"
      }
    value_template: >
      {% if value_json.success %}
        {{ value_json.text | replace('\n', ' ') }}
      {% else %}
        Error: {{ value_json.error }}
      {% endif %}
    scan_interval: 3600  # Call the API every hour


```