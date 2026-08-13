# ESPHome OTA Publisher — 문서

[English](DOCS.md)

## 수동 게시

설정 → 이 add-on 패널 → **Manual publish**. 입력 항목: 노드 이름(기기
YAML의 `ota_device` substitution과 일치해야 함), 칩 종류(**자동**으로
두세요 — 업로드한 이미지 헤더에서 읽어내고, 드롭다운과 다르면 헤더를
따릅니다. 직접 고르는 건 헤더에 칩 ID가 없는 타겟, 즉 ESP8266/RP2040만
해당합니다), 버전, 선택적 제목, 그리고 `firmware.ota.bin` 파일
자체(ESPHome 대시보드 UI에서 받으세요 — "OTA format"). 이 경로는
ESPHome과의 연결이 아예 필요 없습니다 — 곧바로 `Publisher.publish`로
가는데, 이건 자동 경로가 마지막에 쓰는 것과 같은 코드입니다.

ESPHome의 public 포트를 열고 싶지 않거나(아래 참고), 그냥 일회성 기기
하나만 게시할 때 이 방법을 쓰세요.

수동으로 게시한 노드도 기기 테이블에 "manual" 배지와 함께 표시됩니다 —
이 테이블은 ESPHome 대시보드의 기기 목록(닿을 때)과 실제로 디스크에
게시된 것(`Publisher.list_published`, 디렉터리 스캔이라 실제 상태와
어긋나는 별도 추적 파일이 없음)을 합친 겁니다. 이 행에서 **Upload**를
다시 눌러(그 노드용 Manual publish 폼이 미리 채워진 채로 열려서 bin/
매니페스트를 그 자리에서 교체) YAML 스니펫을 복사하거나 **Delete**할 수
있습니다. ESPHome 대시보드에 아예 닿지 않아도 테이블은 계속
렌더링됩니다 — 수동 게시된 행만이라도, 나머지가 왜 없는지 설명하는
배너와 함께 — 예전처럼 아예 실패하지 않습니다(`GET /api/devices`가 이
경우엔 더 이상 502를 내지 않습니다).

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

기기 `livingroom.yaml`이라면:

```
<config>/www/esphome_ota/livingroom.ota.bin       펌웨어
<config>/www/esphome_ota/livingroom.ota.bin.md5   16진수 다이제스트 (md5_url용)
<config>/www/esphome_ota/livingroom.json          매니페스트 (update.http_request용)
```

매니페스트의 `ota.path`는 **상대 경로**이고 `?v=<md5 앞자리>`가
붙습니다:

```json
{"name":"Living Room","version":"1.0.0","builds":[{"chipFamily":"ESP32-C3",
 "ota":{"md5":"5bf1…","path":"livingroom.ota.bin?v=5bf1f6e2","summary":"…"}}]}
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

## 패키지 — `ota_server/ota.yaml`

```yaml
substitutions:
  ota_device: livingroom

packages:
  ota: !include ota_server/ota.yaml

esphome:
  project:
    name: "you.something"
    version: "1.0.0"      # bump this to offer an update
```

이 include 하나로 강제 설치 버튼과 Update 엔티티가 둘 다 들어갑니다.
예전 파일명 `ota_server/update.yaml`과 `ota_server/flash_button.yaml`도
`ota.yaml`과 같은 내용으로 계속 생성되므로, 기존 기기 설정은 그대로
동작하고 — 이제는 두 엔티티를 모두 갖게 됩니다.

버튼은 아무것도 파싱하지 않습니다 — `.bin`을 받아서 MD5 16진수
문자열을 대조할 뿐입니다. Update 엔티티는 먼저 JSON 매니페스트를 받아서
파싱하는데, 이건 Home Assistant 앞단의 프록시/CDN이 개입할 수 있는
지점이 하나 더 생기는 셈입니다(
[문제 해결](#매니페스트에서-json-파싱-실패-update-엔티티에서만) 참고).
매니페스트 fetch가 실패하면 버튼을 쓰세요.

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

### 업데이트 엔티티

기기는 `ESPHOME_PROJECT_VERSION`을 현재 버전으로 보고해서 매니페스트의
`version`과 비교합니다. **`esphome.project` 블록이 없으면** 기기는
ESPHome 릴리스 문자열을 대신 보고하고, add-on도 매니페스트 버전을
그걸로 게시하게 됩니다 — 즉 본인 설정을 바꿔도 업데이트가 안 뜨고,
ESPHome 자체를 업그레이드했을 때만 뜹니다. UI가 이 상태인 기기를
표시해줍니다. 버튼은 버전 없이도 동작합니다.

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

### 기기별로 주소 오버라이드하기

패키지는 `ota_base_url` substitution을 정의하는데, 기본값은
add-on에 설정된 `base_url`입니다. ESPHome은 메인 설정의
`substitutions:`를 패키지의 동일 이름 substitution 위에 덮어쓰므로,
다른 주소가 필요한 기기 — 예를 들어 두 번째 원격 사이트 — 는 생성된
파일을 건드리지 않고 오버라이드할 수 있습니다:

```yaml
substitutions:
  ota_device: livingroom
  ota_base_url: https://second-site.example
```

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
수 있습니다.

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
