# ESPHome OTA Publisher — 문서

[English](DOCS.md)

## 수동 게시 (추천)

테이블에는 **등록한** 기기가 나옵니다. 펌웨어를 아직 올리지 않아도
행이 남아서, ESPHome에 다녀와도 사라지지 않습니다.

1. 아래에서 YAML을 고르고 버전을 적은 뒤 **등록**합니다.
2. 그 행에서 **`+ OTA 적용`** 버튼을 클릭하여 기기 YAML에 OTA 패키지를 원클릭으로 자동 주입합니다 (또는 스니펫을 직접 복사할 수도 있습니다).
3. ESPHome에서 컴파일합니다.
4. ESPHome에서 **Install → Advanced options → Download firmware binary →
   OTA update**로 받은 `.bin` 파일을 같은 행에 드래그 앤 드롭하거나 **`바이너리 업로드`** 버튼으로 올립니다.
   Modern/Factory가 아니라 **OTA update**만 해당합니다.

게시 슬러그는 YAML 파일명입니다(`livingroom.yaml` → `livingroom.ota.bin` /
`livingroom.json`). 칩은 이미지 헤더에서 읽습니다. **YAML 설정**은 기기 YAML 파일에
OTA 패키지가 주입되었는지 여부를 나타내며, **YAML 버전**은 컴파일 시
기기 YAML/래퍼에 적용되는 `esphome.project.version`입니다 (그 칸이나 스니펫 패널에서 변경 가능).
**게시된 펌웨어**는 `/local`에 실제로 배포된 바이너리 버전입니다. 새 펌웨어를 게시하면
다음 컴파일을 위해 YAML 버전이 자동으로 1씩 올라갑니다.

ESPHome 연결은 필요 없습니다 — `Publisher.publish`로 가며, 자동 경로가
마지막에 쓰는 코드와 같습니다.

ESPHome public 포트를 열고 싶지 않거나, 일회성 기기만 게시할 때 쓰세요.

게시된 행에서 다시 업로드, 원클릭 OTA 적용/해제, YAML 스니펫 확인, **`비활성화 (숨김)`**(애드온 저장소에 안전하게 보관하고 `/local`에서 바이너리만 숨김), **`활성화 (공개)`**(보관된 바이너리를 `/local`에 즉시 재배포), 또는 **`기기 삭제`**(목록에서 완전 제거)를 할 수 있습니다. 대시보드에
닿는 게시 기기면 그 행에 Build & publish도 남습니다.

## 필요한 ESPHome add-on 설정 (자동 빌드 & 게시 경로에만 해당)

위의 수동 경로는 이게 전혀 필요 없습니다. 이 섹션은 이 add-on이
ESPHome Device Builder의 WebSocket API에서 직접 빌드하고 펌웨어를
받아오길 원할 때만 해당됩니다. 원래 접근 경로인 HA 사이드바 / Ingress는
이 용도로는 막다른 길입니다 — ingress 사이트는 `ingress_peer_guard`
미들웨어(`esphome_device_builder/helpers/auth.py`)로 보호되는데, 이건
TCP peer가 loopback이거나 Supervisor 컨테이너 자신의 고정 주소
(`172.30.32.2`)일 때만 연결을 허용합니다. Ingress는 HA의 인증된
브라우저 프록시가 통과하라고 있는 것이지, 한 add-on이 다른 add-on을
호출하라고 있는 게 아닙니다. 그 외의 출발 IP는 — 같은 바인딩된 포트로
직접 접근하는 이웃 add-on을 포함해서 — 어떤 주소/포트로 걸어도
WebSocket 핸드셰이크에서 그냥 HTTP 403을 받습니다.

들어갈 수 있는 유일한 다른 문은 ESPHome의 *public* 포트인데,
device-builder는 **둘 다** 참일 때만 그걸 바인딩합니다(하나만으론 안
열립니다):

1. Network 탭 → `6052/tcp`를 호스트 포트에 매핑
2. Options → `leave_front_door_open` 켜기

둘 다 설정하면 그 포트는 인증 전혀 없이 전체 대시보드를 서빙합니다 —
설정 파일, `secrets.yaml`(Wi-Fi 자격증명), 재빌드/재플래시 — 닿을 수
있는 누구에게나요. 이 add-on 자체의 `/local` 게시와 달리, 이건
펌웨어 파일로 범위가 한정돼 있지 않고, 외부 클라우드 터널 경로도 타지
않습니다 — 오늘날 이 add-on의 `/local` 파일들처럼 LAN에서만 보입니다.
LAN이 인증 없는 서비스를 두기에 편한 존이 아니라면 이걸 켜지 마세요;
그러면 add-on은 그냥 대시보드를 못 찾는다고 계속 로그만 남길 겁니다.

## 동작 원리

1. `base_url`을 결정합니다(아래 Options 표 참고) — 옵션으로 지정한 게
   없으면 HA에 설정된 외부 URL을 `GET /core/api/config`로 가져옵니다
   (`homeassistant_api: true`가 이미 설정돼 있어야 함) — LAN 밖 기기가
   실제로 필요로 하는 주소가 이거니까요.
2. **자동 경로:** Supervisor를 통해 ESPHome add-on의 매핑된 public
   포트를 찾고(`GET /addons`, 이어서 `/addons/<slug>/info`) 거기로
   WebSocket API를 연결합니다 — ingress 포트가 이 용도로 안 되는 이유는
   위 참고. `firmware/compile` → `firmware/follow_job` →
   `firmware/download_token` → `GET /api/firmware/download` 순서로
   실행하는데, 대시보드 프론트엔드가 하는 것과 같은 시퀀스입니다.
   **수동 경로:** 업로드된 파일을 그대로 씁니다.
3. 어느 쪽이든: MD5를 계산하고, `chipFamily`를 알아낸 뒤,
   `<config>/www/<publish_dir>/`에 파일 세 개를 씁니다.
4. Home Assistant가 그걸 `/local/<publish_dir>/…`로 인증 없이
   서빙합니다, 기기가 닿을 수 있는 어떤 주소로든.

## 옵션

| 옵션 | 기본값 | 의미 |
|---|---|---|
| `dashboard_url` | *(자동)* | ESPHome 대시보드 기본 URL을 직접 지정, 예: `http://172.30.32.1:6052`(매핑된 public 포트, ingress 포트 아님 — 위 참고). 비워두면 자동 감지. |
| `dashboard_token` | *(비어있음)* | `ESPHOME_USERNAME`/`ESPHOME_PASSWORD`로 시작된 대시보드에만 필요. |
| `publish_dir` | `esphome_ota` | `<config>/www/` 밑의 폴더 이름, 그래서 `/local/` 밑 경로도 이걸 씁니다. |
| `base_url` | *(자동)* | 기기가 Home Assistant에 닿는 방법, 예: `https://your-tunnel-domain`. 결정 순서: 이 옵션(설정됐으면) → HA에 설정된 외부 URL(설정 → 시스템 → 네트워크) → 최후 수단으로 호스트의 LAN 주소(경고로 로그 남음 — 이건 같은 LAN에 있는 기기에만 동작하는데, 그런 기기는 대체로 이 add-on 자체가 필요 없습니다). 생성되는 패키지를 채우는 데만 쓰입니다. |
| `log_level` | `info` | `debug`로 하면 모든 대시보드 프레임을 출력합니다. |

## 게시된 파일

등록된 기기 `livingroom` (발급된 시크릿 토큰 `a8f3b9c2e17d904f8e5b6c7a1d2e3f4a`)이라면:

```
<config>/www/esphome_ota/livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a.ota.bin       펌웨어 (보호됨)
<config>/www/esphome_ota/livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a.ota.bin.md5   16진수 다이제스트 (md5_url용)
<config>/www/esphome_ota/livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a.json          매니페스트 (update.http_request용)
```

### 🔒 시크릿 토큰 슬러그 (외부 스캔 차단 & 불변 URL)
Home Assistant의 `/local/` 경로는 기본적으로 인증 없이 열려 있으며, 디렉토리 목록 조회는 차단(`404 Not Found`)되어 있습니다. 신규 등록 기기는 파일명에 128비트 암호학적 난수 토큰을 슬러그(`ota_slug`)로 부여받습니다.

* **추측 공격 원천 차단**: 외부 해커나 자동화 봇이 32자리 난수 파일명을 유추하거나 사전 공격(Dictionary Attack)을 시도할 수 없습니다.
* **불변 URL & 고립/벽돌 위험 제로**: 토큰은 기기 등록 시 최초 1회 생성되어 기기 YAML 래퍼에 영구 고정됩니다. 펌웨어 배포 시 URL이 바뀌지 않으므로 원격 기기가 고립되거나 벽돌이 될 위험이 전혀 없습니다.
* **토큰 변경 (로컬 접근 필요)**: 기존 기기의 토큰을 변경하면 OTA URL 자체가 바뀌므로 기기의 이전 원격 업데이트 경로가 끊어집니다. 따라서 토큰을 재발급하려면 대시보드에서 기기를 삭제 후 재등록하고, 새로 생성된 스니펫을 **로컬 접근(USB 시리얼 또는 동일 LAN OTA)**을 통해 최초 1회 다시 플래시해야 합니다.

매니페스트의 `ota.path`는 **상대 경로**이고 `?v=<md5 앞자리>`가
붙습니다:

```json
{"name":"Living Room","version":"1.0.0","builds":[{"chipFamily":"ESP32-C3",
 "ota":{"md5":"5bf1…","path":"livingroom_a8f3b9c2e17d904f8e5b6c7a1d2e3f4a.ota.bin?v=5bf1f6e2","summary":"…"}}]}
```

상대 경로인 이유는 ESPHome이 이걸 매니페스트 자신의 URL 기준으로
풀어내기 때문입니다 — 그래서 기기가 매니페스트를 LAN 주소로 받았든
원격 터널로 받았든 같은 파일이 그대로 동작하고, 아무것도 다시 쓸 필요가
없습니다.

캐시버스터가 붙는 이유는 Home Assistant가 `/local` 밑 모든 것에 31일
`Cache-Control`을 찍기 때문입니다. LAN을 직접 거치면 무해합니다(ESP는
아무것도 캐싱하지 않으니까), 하지만 Home Assistant 앞에 있는
프록시 — 예를 들면 Cloudflare 터널 — 는 기본적으로 `.bin`을 캐싱해서
한 달 묵은 펌웨어를 신나게 내려줄 수 있습니다. `.json`은 기본적으로
캐싱되지 않아서, 매니페스트는 항상 최신 상태를 유지하고 빌드마다 새
URL을 가리킵니다.

바이너리는 임시 파일에 쓴 뒤 `os.replace`로 자리에 넣습니다. rename은
디렉터리 엔트리만 교체하고, 다운로드 중인 기기는 계속 옛날 inode를
읽기 때문에, 다운로드 도중 재게시가 일어나도 업데이트가 깨지지
않습니다.

## 패키지 — `ota_server/*.yaml`

파일 세 개, 각자 이름 그대로의 내용만 담고 있습니다:

| 파일 | 내용 |
|---|---|
| `update.yaml` — **추천** | Update 엔티티만 |
| `flash_button.yaml` — 대안 | 강제 설치 버튼만 |
| `ota.yaml` | 둘 다 — `update.yaml`과 `flash_button.yaml`을 같이 `!include` 못 해서 있는 파일입니다(둘 다 `http_request:`/`ota:`를 정의하는데, ESPHome은 두 패키지의 같은 최상위 키를 병합하지 않습니다) |

```yaml
packages:
  ota: !include ota_server/devices/livingroom.yaml
```

래퍼(`ota_server/devices/<yaml-stem>.yaml`)가 `ota_device`, OTA 엔티티,
`esphome.project`를 넣습니다. project 블록을 기기 YAML에 적거나 버전을
올릴 필요는 없습니다. 버전은 등록할 때 정하고, 다음 칸에서 바꿉니다.
게시 후에는 래퍼 버전이 올라가서 다음 컴파일이 새 업데이트가 됩니다.
공유 패키지가 `safe_mode:`도 켭니다 — `http_request` OTA는
`platform: esphome`과 달리 이걸 자동으로 켜지 않습니다.

Update만 또는 버튼만이면 같은 폴더의 `livingroom.update.yaml` /
`livingroom.button.yaml`을 include하세요. 예전 방식
(`substitutions.ota_device` + `!include ota_server/update.yaml`)도 동작합니다.

**Update 엔티티가 기본 추천 방식입니다** — 버전 추적이 되고, HA에
Install 버튼이 생깁니다. 먼저 JSON 매니페스트를 받아서 파싱하는데,
일부 환경에서는 Home Assistant 앞단의 프록시/CDN이 여기 개입할 수
있습니다([문제 해결](#매니페스트에서-json-파싱-실패-update-엔티티에서만)
참고). 이 특정 증상을 겪으면 `!include`를 `.button.yaml` 래퍼로
바꾸세요 — 아무것도 파싱하지 않는 대신 버전 추적은 없습니다. 한 기기에
둘 다 필요하면 stem 래퍼(`devices/livingroom.yaml`)를 쓰세요.

### 업데이트 엔티티

기기는 `ESPHOME_PROJECT_VERSION`을 현재 버전으로 보고해서 매니페스트의
`version`과 비교합니다. 생성된 래퍼가 `esphome.project`를 넣으므로 기기
YAML에 그 블록을 적을 필요는 없습니다. 예전 `ota_device` include만 쓰고
project가 없으면 기기는 ESPHome 릴리스 문자열을 보고하고, 그때는
ESPHome 자체를 업그레이드했을 때만 업데이트가 뜹니다. 버튼은 버전 없이도
동작합니다.

Install을 눌렀을 때 실제로 다운로드가 되려면 디바이스의 `update:`
상태가 이미 `AVAILABLE`이어야 합니다 — 이 상태는 오직 이전에 성공한
매니페스트 fetch(자동으로 `update_interval`마다, 또는 `update.check`
액션으로)에서만 나옵니다. `update.check`는 비동기라서, 같은 버튼 누름
안에서 바로 이어서 `update.perform`을 호출하면 fetch가 끝나기 전에
설치가 실행될 수 있습니다. 대신 `update:` 엔티티에 `on_update_available`을
쓰세요 — 그러면 fetch가 실제로 업데이트를 확인한 뒤에만 설치가
일어납니다:

```yaml
button:
  - platform: template
    name: Check for update
    on_press:
      - update.check: ota_update

update:
  - id: !extend ota_update
    on_update_available:
      - update.perform: ota_update
```

### 강제 설치 버튼

버전 추적이 없습니다. 버튼을 누르면 `ota.http_request.flash`가
`.ota.bin` URL로 `md5_url`과 함께 실행되고, 다이제스트가 받은 것과 안
맞으면 기기는 기존 펌웨어를 그대로 유지합니다.

`url`/`md5_url`은 누를 때마다 랜덤 `?r=<random_uint32()>`를 붙이는
람다라서, 누를 때마다 Home Assistant 앞단의 어떤 프록시나 CDN에게도
매번 새로운 캐시 미스가 됩니다.

생성된 버튼의 id는 `ota_flash_button`입니다. `ota.http_request.flash`
호출을 중복 작성하는 대신, 기기 YAML의 다른 곳에서 `button.press`로
이걸 눌러주세요 — 예를 들어 물리 GPIO 버튼을 누르면 최신 게시본을
플래시하게:

```yaml
button:
  - platform: gpio
    pin: GPIO0
    name: Flash Button
    on_press:
      - button.press: ota_flash_button
```

### 기기별로 주소 오버라이드하기

패키지는 `ota_base_url` substitution을 정의하는데, 기본값은
add-on에 설정된 `base_url`입니다. ESPHome은 메인 설정의
`substitutions:`를 패키지의 동일 이름 substitution 위에 덮어쓰므로,
다른 주소가 필요한 기기 — 예를 들어 두 번째 원격 사이트 — 는 생성된
파일을 건드리지 않고 오버라이드할 수 있습니다:

```yaml
substitutions:
  ota_base_url: https://second-site.example

packages:
  ota: !include ota_server/devices/livingroom.yaml
```

## 보안: 펌웨어 내 민감 정보 유출 방지

<a id="보안-펌웨어-내-민감-정보-유출-방지"></a>

### `/local` 경로의 보안 모델

Home Assistant의 `<config>/www/` 디렉토리는 `/local/` 경로로 매핑되며, **설계상 인증 없이(Unauthenticated)** 서빙됩니다. 이는 프론트엔드 Lovelace 카드, 아이콘, 미디어 파일 등을 로그인 세션 없이 빠르게 브라우저에서 로드할 수 있도록 하기 위한 Home Assistant의 기본 동작 방식입니다.

하지만 이로 인해 Home Assistant가 외부 인터넷(공개 도메인, Cloudflare 터널, 포트 포워딩, Nabu Casa 등)으로 연결되어 있다면, **`/local/` 경로에 게시된 `.ota.bin` 펌웨어와 `.json` 매니페스트 파일은 URL만 알면 누구나 다운로드할 수 있습니다.**

### 위험 요소: 펌웨어 바이너리 내 평문 비밀 정보 노출

일반적인 ESPHome 튜토리얼에서는 다음과 같이 YAML 파일에 Wi-Fi 비밀번호나 키를 직접 작성하도록 안내하는 경우가 많습니다:

```yaml
# ❌ 보안 취약: /local에 공개 배포하는 펌웨어에 비밀 정보를 직접 작성하지 마세요
wifi:
  ssid: "MyHomeNetwork"
  password: "MySuperSecretPassword"

api:
  encryption:
    key: "my_static_secret_encryption_key_here..."

ota:
  - platform: esphome
    password: "my_ota_password"
```

ESPHome이 코드를 컴파일할 때, YAML에 적힌 문자열 리터럴들은 바이너리의 `.rodata` 섹션에 **평문(Plaintext)** 그대로 포함됩니다. 악의적인 공격자가 해당 `.bin` 파일을 다운로드하여 `strings firmware.bin` 명령어 등을 실행하면 Wi-Fi SSID, 비밀번호, API 암호화 키, OTA 비밀번호, 백업 AP 비밀번호 등을 손쉽게 추출할 수 있습니다.

### 해결책: 공식 팩토리 펌웨어 모범 사례 (비밀 정보 0개 원칙)

가장 안전하고 올바른 해결책은 [Home Assistant Voice PE 팩토리 펌웨어](https://github.com/esphome/home-assistant-voice-pe/blob/dev/home-assistant-voice.factory.yaml)와 같은 공식 하드웨어처럼 **컴파일되는 바이너리에서 모든 고정 비밀 정보를 완전히 제거**하는 것입니다.

바이너리 내에 비밀 정보가 포함되어 있지 않다면, 펌웨어가 `/local`을 통해 외부에 공개되더라도 보안상 안전합니다.

#### 1. `esp32_improv` 또는 `improv_serial`을 통한 동적 Wi-Fi 프로비저닝
YAML에 Wi-Fi 비밀번호를 하드코딩하는 대신, 최초 부팅 시 블루투스(BLE) 또는 USB WebSerial을 통해 Wi-Fi 정보를 주입받도록 설정합니다. 자격증명은 바이너리가 아닌 기기의 NVS(Flash 영구 저장소)에 런타임 저장됩니다:

```yaml
# ✅ 안전함: BLE / WebSerial을 통한 동적 프로비저닝
esp32_improv:
  # 선택 사항: 물리 버튼으로 승인 절차 추가 가능
  # authorizer: my_button

wifi:
  # ssid와 password를 하드코딩하지 않습니다! 초기 설정 시 NVS에 안전하게 저장됩니다.

# 필요 시 USB WebSerial 설정 지원:
improv_serial:
```

#### 2. 동적 / 무작위 API 암호화 키 사용
YAML에 고정된 암호화 키를 지정하지 않습니다. `encryption:` 블록을 빈 상태로 두면 Home Assistant에 기기를 등록(Adoption)할 때 Home Assistant가 고유한 암호화 키를 동적으로 생성하여 기기의 NVS에 저장합니다:

```yaml
# ✅ 안전함: Home Assistant가 등록 시 암호화 키를 동적으로 생성 및 관리
api:
  encryption:
```

#### 3. 고정 OTA 비밀번호 및 백업 비밀번호 제거
YAML에 고정된 OTA 비밀번호나 백업 AP 비밀번호를 포함하지 않습니다:

```yaml
# ✅ 안전함: 하드코딩된 비밀번호 없음
ota:
  - platform: http_request
```

#### 4. 스마트 자동 숨김 및 바이너리 비활성화 (보안 극대화)
펌웨어가 `/local` 경로에 항상 노출되는 것을 방지하기 위해 **스마트 자동 숨김(Auto-Deactivate)** 기능을 지원합니다:
- **업데이트 성공 시 즉시 자동 숨김 (`⚡ 자동 숨김: 완료 시` - 기본 추천)**:
  - 기기가 새 펌웨어를 다운로드하고 재부팅하여 Home Assistant에 새 버전 적용 완료를 보고하는 순간, 애드온이 `/local` 경로에서 바이너리(`.bin`)를 자동으로 제거(숨김)합니다.
  - 바이너리는 애드온 내부 전용 저장소(`/data/firmware`)에 보관되므로 언제든 원클릭으로 다시 활성화할 수 있습니다.
- **안전 타임아웃 타이머 (`⏱ 지정 시간 후 숨김`)**:
  - 다른 HA 인스턴스 기기나 엔티티가 없는 경우, 배포 후 지정된 시간(기본 12시간)이 지나면 자동으로 바이너리를 숨김 처리합니다.
- **릴리즈 노트 (요약 메모) 지원**:
  - 펌웨어 업로드 시 변경 사항 메모를 입력하면 Home Assistant의 Update 엔티티 창에 변경 내역이 그대로 표시됩니다.
- **다중 기기 일괄 관리 (Batch Actions)**:
  - 테이블 좌측 체크박스를 선택하여 여러 기기를 한 번에 **[일괄 비활성화]**, **[일괄 활성화]**, **[일괄 OTA 적용]**, **[일괄 삭제]**할 수 있습니다.
- **자동 설정 백업 (`.bak`)**:
  - `+ OTA 적용` 클릭 시 수정 전 원본 YAML이 `<config>/esphome/<node>.yaml.bak`에 안전하게 보관됩니다. 이전 설정으로 수동 되돌리기가 필요한 경우 해당 `.bak` 파일을 복원하시면 됩니다.

## 문제 해결

**"Restart Home Assistant once."** — `/local`은 시작할 때 한 번만
등록되는데, `www` 폴더에 대한 `isdir` 체크 뒤에 있습니다. add-on이 그
폴더를 새로 만들어야 했다면, Home Assistant는 아직 그걸 모릅니다.

**"Could not find the ESPHome dashboard."** — ESPHome add-on이
실행 중이어야 하고, 포트 6052가 매핑돼 있고 `leave_front_door_open`이
켜져 있어야 합니다(위
[필요한 ESPHome add-on 설정](#필요한-esphome-add-on-설정-자동-빌드--게시-경로에만-해당)
참고 — 둘 다 아니면 public 포트가 안 열려있고, 이 add-on이 닿을 다른
곳도 없습니다). 그래도 계속 실패하면 `dashboard_url`을 직접 설정하세요,
예: `http://172.30.32.1:6052`.

**기기 목록이 메시지에 "HTTP 403"이 담긴 HTTP 502를 반환** — 이
add-on이 public 포트가 아니라 ingress 포트로 시도한 겁니다(`dashboard_url`을
직접 손으로 설정했을 때만 가능). 매핑된 public 포트를 대신
가리키게 하세요.

**기기 목록이 다른 이유로 HTTP 502를 반환** — 이제 add-on 로그에 실제
`DashboardError` 메시지가 남습니다(502를 반환하는 바로 그 지점에서
warning으로 로그됨). 재현한 뒤 로그를 다시 확인하세요 — 거기 나온
에러 텍스트가 UI에 뜨는 것과 같은 것이지, 일반적인 프록시 실패가
아닙니다.

**Update 엔티티가 아예 안 뜸** — UI에서 `chipFamily`를 확인하세요.
ESPHome은 이걸 `ESPHOME_VARIANT`와 정확한 문자열 비교로 대조하고,
안 맞으면 아무것도 보고하지 않습니다 — 기기 로그에는 `Failed to parse
JSON from …`으로만 찍히고, Home Assistant에서는 Update 엔티티가 계속
*알 수 없음*입니다. 게시되는 값은 이미지 헤더의 칩 ID에서 나오는데,
add-on이 모르는 ID면 이제 추측하지 않고 게시를 거부합니다(로그에 해당
ID가 찍히니 버그로 알려주세요). LibreTiny 타겟(BK72xx, RTL87xx)은
지원하지 않습니다 — 그 variant 문자열은 칩마다 달라서 add-on이 유도할
수 없습니다.

**백업 용량이 늘어남** — `<config>/www`는 Home Assistant 백업에
포함되는데, 게시된 기기당 대략 1–2MB입니다. delete 엔드포인트를
쓰거나 폴더를 직접 비워서 기기 파일을 지우세요.

**펌웨어가 누구나 읽을 수 있음** — `/local`은 설계상 인증이 없습니다.
그게 바로 로그인할 수 없는 기기에서도 닿을 수 있게 만드는 방법입니다.
게시한 건 뭐든 Home Assistant의 HTTP 포트에 닿을 수 있는 누구나 읽을
수 있습니다. 기기 YAML에 비밀 정보가 포함되지 않도록 위의
[보안 모범 사례](#보안-펌웨어-내-민감-정보-유출-방지)를 반드시 따르세요.

**OTA 중 MD5 불일치 (`Aborting due to MD5 mismatch`)** — 보통 Home
Assistant 앞단의 캐싱 프록시(가장 흔하게는 Cloudflare 터널)가 재게시
이후에도 옛날 `.ota.bin`을 계속 내려주는 경우입니다. 생성된 패키지는
이제 펌웨어 URL에 캐시버스터가 붙어서(위
[강제 설치 버튼](#강제-설치-버튼) 참고), 새로 생성된 `ota.yaml`이라면
이 문제가 안 나야 정상입니다 — 이 항목은 이 수정 이전(0.3.5 이전)에
컴파일된 고정 URL `flash_button.yaml`을 아직 쓰는 기기이거나, 쿼리
문자열 자체를 무시하는 캐싱 레이어(드물지만 일부 CDN은 그렇게 설정
가능)일 때를 위한 겁니다. 지금 origin에 실제로 있는 것과 실제로
서빙되고 있는 것을 비교해서 확인하세요:

```bash
curl -s "$BASE/local/$PUBLISH_DIR/$NODE.ota.bin.md5"
curl -s "$BASE/local/$PUBLISH_DIR/$NODE.ota.bin" | md5sum
```

이 둘이 다르다면, 응답 헤더(`curl -sD -`)에서 `cf-cache-status: HIT`
(또는 그에 준하는 프록시 캐시 헤더)와 `.bin` 요청의 오래된
`age`/`last-modified`를 확인하세요 — 그게 add-on이 아니라 캐시가 옛날
바이트를 서빙하고 있다는 확증입니다. 해결법:

- **기기를 한 번 재컴파일 & 재플래시하세요**, 지금 되는 아무 방법으로나
  (USB, 또는 ESPHome 대시보드를 통한 수동 펌웨어 설치). 그러면 새로운
  랜덤 `?r=`가 붙은 패키지를 받아서, 그 이후 누를 때마다 이 문제가
  끝납니다.
- **CDN이 쿼리 문자열을 캐싱 기준에서 무시한다면**, 명시적인 캐시
  우회 규칙을 대신 추가하세요. Cloudflare라면: Rules → Cache Rules →
  경로 매칭(예: `contains` `.ota.bin`) → Cache eligibility:
  **Bypass cache**.

일회성으로 이미 걸려있는 캐시라면 그 특정 `.ota.bin` URL만 수동으로
퍼지하면 바로 풀립니다.

**매니페스트에서 JSON 파싱 실패 (Update 엔티티에서만)** — 기기는
`source:`에 정상적으로 닿았는데, 받아온 게 JSON으로 파싱이 안 된
경우입니다. Cloudflare 터널을 쓰는 `base_url`에서 실제로 확인된
사례: 밖에서 확인할 때마다(`curl -s ".../<node>.json"`) 디스크의
파일은 매번 정상이었는데, 기기 자신의 fetch는 계속, 즉시, 반복적으로
실패했습니다 — 위의 MD5 불일치처럼 캐시/staleness 증상이 아니고,
재게시와도 무관합니다.

유력하지만 확인은 안 된 용의자: 응답 압축입니다. `curl -H
"Accept-Encoding: gzip, deflate" ".../<node>.json"`로 요청하면
`content-encoding: gzip`과 실제로 gzip된 본문이 이 add-on의
Cloudflare 프론트 `/local`에서 돌아옵니다 — 즉 요청이 압축을
요구하면 Cloudflare가 이 응답을 gzip으로 압축해서 줄 수 있고, 실제로
그렇게 한다는 게 확인된 겁니다. ESPHome의 `http_request` 컴포넌트는
gzip을 압축 해제하지 않습니다. 만약 기기의 요청이 어떤 경로로든
압축을 요구하게 된다면(자체 기본값, 중간의 네트워크 미들박스, 기기와
Cloudflare 사이 어디든) 압축된 바이트를 그대로 받아서 JSON 파서에
넘기게 됩니다 — 정확히 이 에러이고, 정확히 이 "닿긴 했는데 파싱이 안
되는" 패턴입니다.

테스트 방법: Cloudflare 대시보드 → **Speed → Optimization → Brotli**
→ 끄기, 그다음 디바이스의 매니페스트 체크를 다시 시도하세요. 그걸로
해결되면 압축이 원인이었던 것이니, 이 zone 전체에서 계속 꺼두거나
(펌웨어 매니페스트는 몇백 바이트라 압축해봐야 이득이 없습니다),
Configuration Rules / Response Header Transform Rules가 있는
플랜이라면 `/local/*`로만 예외 범위를 좁히세요.

원인이 뭐든 가장 간단한 해결책: **Update 엔티티의 Install 대신 강제
설치 버튼을 쓰세요.** `.ota.bin`을 받고 `.ota.bin.md5`는 그냥 텍스트로
읽어서, 압축되거나 어떻게든 망가진 응답이 깨질 JSON 파싱 단계 자체가
없습니다.

**수동 게시에서 칩 종류가 거부됨** — **자동** 상태에서 이 오류가 나면
업로드한 파일 헤더에서 칩 ID를 읽지 못한 것입니다. ESP32 이미지가 아니거나
(ESP8266/RP2040 — 드롭다운에서 직접 고르세요), 애초에 `.ota.bin`이 아닌
파일입니다. 직접 고른 값은 이 경우에만 그대로 쓰이고, 헤더에 칩 ID가 있으면
언제나 헤더가 드롭다운을 이깁니다 — 그래서 ESP32-C3 바이너리를 실수로
`ESP32`로 게시할 수 없습니다.
