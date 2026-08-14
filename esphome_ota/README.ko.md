# ESPHome OTA Publisher

[English](README.md)

ESPHome 자체의 로컬/mDNS OTA가 닿지 않는 기기용입니다 — 보통 집 네트워크
바깥에 있어서 Home Assistant의 원격/클라우드 터널 주소로만 접근 가능한
경우입니다. Home Assistant와 같은 네트워크에 있는 기기라면 이건 필요 없고,
ESPHome 자체 내장 OTA를 그냥 쓰면 됩니다.

펌웨어와 그 MD5, ESP-Web-Tools 매니페스트를 `<config>/www/`에 게시하는데,
이 경로는 Home Assistant가 이미 `/local/`로 인증 없이 서빙하고 있는
곳이라 — 내부 주소든 외부 터널이든 둘 다에서 닿고, 이 add-on 쪽에서
따로 열어야 하는 포트도 없습니다.

```
                                                <config>/www/esphome_ota/
                                                        │
                              https://<your-external-address>/local/esphome_ota/…
                                                        ▼
                                                 your remote devices
```

펌웨어를 저기에 올리는 방법은 두 가지입니다:

## A. 수동 게시 — 별도 설정 필요 없음

YAML을 고르고 버전을 적어 **등록**하세요. 목록 행에서 스니펫을 복사하고
ESPHome에서 컴파일한 다음, **Install → Advanced options → Download firmware
binary → OTA update**로 받은 `.bin`을 같은 행에서 게시합니다. 게시 이름은 YAML
파일명입니다(`livingroom.yaml` → `livingroom.ota.bin`). 칩은 이미지에서
읽고, **버전**은 게시된 펌웨어, **다음**은 다음 컴파일이 보고할 값입니다
— 그 칸에서 바로 바꿀 수 있습니다. ESPHome add-on 쪽은 바꿀 필요 없습니다.

## B. 여기서 빌드 & 게시 — ESPHome 쪽 설정이 필요함

이 add-on은 ESPHome Device Builder add-on을 직접 조종해서(그 대시보드
UI가 쓰는 것과 같은 API) 원클릭으로 빌드 & 게시할 수 있습니다. 원래
접근 경로인 HA 사이드바 / Ingress는 설계상 loopback과 Supervisor로만
막혀있어서, 옆에 있는 다른 add-on은 거기로 못 들어갑니다. 대신 ESPHome의
**public** 포트를 써야 하는데, 이건 **ESPHome** add-on 자체 설정에서
포트 `6052`를 매핑하고 `leave_front_door_open`을 켜야 한다는 뜻입니다.
그렇게 하면 ESPHome 대시보드 — 설정 파일, `secrets.yaml`, 재빌드/재플래시 —
가 LAN 안에서 인증 없이 열립니다(외부 터널을 통하는 게 아니라 로컬
네트워크에서만). 이 트레이드오프가 신경 쓰이신다면 켜기 전에
[DOCS.ko.md](DOCS.ko.md#필요한-esphome-add-on-설정-자동-빌드--게시-경로에만-해당)를
먼저 보세요. 그만한 가치가 없다고 느껴지면 그냥 A를 쓰세요.

## ESPHome의 빌드 폴더를 그냥 읽으면 안 되나요?

안 됩니다. ESPHome이 add-on으로 돌아갈 때 `CORE.data_dir`은
`/data`(그 add-on 전용 볼륨)로 고정돼 있어서, 컴파일된 바이너리가
`/config/esphome` 밑에는 절대 안 나타나고, Supervisor도 다른 add-on의
데이터에 닿는 매핑을 제공하지 않습니다. 공유되는 건 YAML 소스뿐입니다.

## 뭘 얻게 되나요

`<config>/esphome/ota_server/` 밑에 ESPHome 패키지 세 개가 생성되는데,
각각 이름 그대로의 내용만 담고 있습니다:

| 파일 | 얻는 것 | 필요한 것 |
|---|---|---|
| `update.yaml` — 추천 | HA에 Install 버튼이 달린 **Update 엔티티** | 없음 — 래퍼가 `esphome.project`를 넣음 |
| `flash_button.yaml` — 대안 | 항상 최신 게시본을 설치하는 **버튼** | 없음 |
| `ota.yaml` | 위 둘 다 함께 | `update.yaml`과 `flash_button.yaml`은 같이 `!include` 못 함 — 둘 다 `http_request:`/`ota:`를 정의하므로 |

공통 파일 대신 기기별 래퍼를 include하세요:
`packages: ota: !include ota_server/devices/livingroom.yaml` (슬러그 = YAML
파일명). 래퍼가 `ota_device`와 버전을 넣습니다. 패키지가 `safe_mode:`도
켭니다 (`http_request` OTA는 `platform: esphome`과 달리 자동으로 안 켭니다).

Update 엔티티는 먼저 JSON 매니페스트를 받아서 파싱합니다. 드물게 Home
Assistant 앞단의 프록시/CDN이 이 응답을 ESPHome의 `http_request`가 처리
못 하는 방식으로 압축하는 환경에서는 `Failed to parse JSON from
.../<node>.json`이 로그에 찍히고 *AVAILABLE* 상태로 못 넘어갑니다. 버튼은
정확히 이 경우를 위한 대안입니다 — 아무것도 파싱하지 않고 `.bin`을
받아 MD5만 확인합니다. 이 증상을 겪으면
[DOCS.ko.md](DOCS.ko.md#매니페스트에서-json-파싱-실패-update-엔티티에서만)
참고.

펌웨어 URL에는 캐시버스터가 붙습니다(매니페스트의 바이너리 경로에
`?v=<md5>`, 버튼은 누를 때마다 랜덤 `?r=`) — 그래서 Home Assistant
앞단의 캐싱 프록시나 CDN(예: Cloudflare 터널)이 재게시 이후에도 옛날
`.ota.bin`을 계속 내려주는 일이 없습니다. 그 수정 이전에 컴파일된
`flash_button.yaml`을 아직 쓰는 기기가 있다면
[DOCS.ko.md](DOCS.ko.md#ota-중-md5-불일치-aborting-due-to-md5-mismatch)를
참고하세요 — 한 번만 재컴파일/재플래시하면(지금 되는 아무 방법으로나)
바로 해결됩니다.

## 설치

1. Home Assistant → 설정 → 애드온 → 저장소에 이 저장소를 추가하세요
2. **ESPHome OTA Publisher**를 설치하고 시작하세요
3. add-on이 Home Assistant 재시작을 요청하면 한 번 해주세요 (`/local`
   정적 경로는 시작할 때 등록됩니다)
4. add-on 패널에서 `base_url` 관련 배너를 확인하세요 — Home Assistant의
   설정된 외부 URL(설정 → 시스템 → 네트워크)에서 자동으로 채워집니다;
   거기 설정된 게 없다면 이 add-on 옵션에서 `base_url`을 직접 설정하세요
5. YAML을 등록하고, 그 행의 스니펫을 기기 설정에 붙여넣으세요(include
   경로는 `ota_server/devices/<yaml 파일명>.yaml`). 컴파일한 뒤
   **Install → Advanced options → Download firmware binary → OTA update**로
   받은 `.bin`을 같은 행에서 게시하세요. 이 패널에서 빌드 & 게시하려면
   위에서처럼 ESPHome public 포트를 켜세요.

옵션과 문제 해결은 [DOCS.ko.md](DOCS.ko.md)를 참고하세요.
