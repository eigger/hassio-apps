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

![add-on 패널: 칩, 게시된 버전, 상태가 보이는 기기 목록](https://raw.githubusercontent.com/eigger/hassio-apps/master/esphome_ota/screenshots/devices.png)

펌웨어를 저기에 올리는 방법은 두 가지입니다:

## A. 수동 게시 — 별도 설정 필요 없음

ESPHome 대시보드에서 직접 `firmware.ota.bin`을 받은 뒤("OTA format"
다운로드), 이 add-on 패널 → **Manual publish** → 노드 이름, 칩 종류,
버전을 입력하고 파일을 업로드하세요. ESPHome 쪽은 아무것도 바꿀 필요
없습니다.

![Manual publish 폼](https://raw.githubusercontent.com/eigger/hassio-apps/master/esphome_ota/screenshots/manual-publish.png)

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

`<config>/esphome/ota_server/`에 ESPHome 패키지 두 개가 생성됩니다:

| 패키지 | 주는 것 | 필요한 것 |
|---|---|---|
| `flash_button.yaml` **(기본 권장)** | 항상 최신 게시본을 설치하는 **버튼** | 없음 |
| `update.yaml` | HA에 Install 버튼이 달린 **Update 엔티티** | 버전을 올릴 `esphome.project` 블록 |

둘 중 하나만 쓰세요 — 둘 다 `ota:`를 정의해서 같이 넣으면 충돌합니다.

HA에 Update 엔티티를 꼭 원하는 게 아니라면 `flash_button.yaml`부터
시작하세요. `update.yaml`은 먼저 JSON 매니페스트를 받아서 파싱한 뒤에야
펌웨어를 받는데, `flash_button.yaml`은 아무것도 파싱하지 않고 그냥
`.bin`을 받아서 MD5만 확인합니다 — Home Assistant 앞단의 프록시/CDN이
개입할 여지가 하나 줄어드는 셈입니다. `update.yaml`에서
`Failed to parse JSON from .../<node>.json`가 로그에 찍히면 그 기기를
`flash_button.yaml`로 바꾸세요 —
[DOCS.ko.md](DOCS.ko.md#매니페스트에서-json-파싱-실패-updateyaml에서만)
참고.

두 패키지 모두 이제 펌웨어 URL에 캐시버스터가 붙습니다(`update.yaml`은
매니페스트의 바이너리 경로에 `?v=<md5>`, `flash_button.yaml`은 누를
때마다 랜덤 `?r=`) — 그래서 Home Assistant 앞단의 캐싱 프록시나
CDN(예: Cloudflare 터널)이 재게시 이후에도 옛날 `.ota.bin`을 계속
내려주는 일이 없습니다. 이 수정 이전에 컴파일된 `flash_button.yaml`을
아직 쓰고 있는 기기가 있다면
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
5. 기기를 게시하고(수동으로, 또는 위에서처럼 ESPHome의 public 포트를 켠
   뒤), 화면에 뜨는 YAML 스니펫을 그 기기의 설정에 붙여넣으세요

![기기 게시 후 뜨는 YAML 스니펫, 복사 버튼 포함](https://raw.githubusercontent.com/eigger/hassio-apps/master/esphome_ota/screenshots/yaml-snippet.png)

옵션과 문제 해결은 [DOCS.ko.md](DOCS.ko.md)를 참고하세요.
