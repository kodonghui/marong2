/** @OnlyCurrentDoc */
// 마롱이 기록 시트. 서버의 tools/report.py --sheet 가 30분마다 탭 내용을 통째로 보내면, 탭마다 지우고 새로 쓴다.
// 처음 한 번:
//   1. 구글 시트를 새로 만들고 확장 프로그램 > Apps Script 에 이 파일 내용을 그대로 붙여 넣고 저장
//   2. 배포 > 새 배포 > 유형 선택: 웹 앱 / 다음 사용자 인증 정보로 실행: 나 / 액세스 권한이 있는 사용자: 모든 사용자
//      > 배포 > 액세스 승인('확인되지 않은 앱'이 나오면 고급 > 이동 > 허용) > 웹 앱 주소(…/exec) 복사
//   3. 노트북에서 bash deploy/ovh.sh sheet url (주소 붙여넣기) → bash deploy/ovh.sh sheet on
// 웹 앱 주소는 비밀번호와 같다(아는 사람은 이 시트에 쓸 수 있음). 채팅·문서에 붙여 두지 않는다.
// 받은 탭 이름·칸대로 쓰므로 탭이 바뀌어도 이 스크립트는 다시 배포하지 않아도 된다. 받은 적 없는 탭은 건드리지 않는다.
// 이 스크립트를 고쳤을 때만: 배포 > 배포 관리 > 연필 > 버전: 새 버전 > 배포(주소는 그대로).

var MAX_CHARS = 49000;   // 칸 하나는 5만 자까지
var CHUNK = 5000;        // 한 번에 쓰는 줄 수
var HEADER_COLOR = '#e8e3f3';

function doPost(e) {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(60000)) return reply({ok: false, error: 'busy'});  // 앞의 갱신이 아직 쓰는 중
  try {
    var data = JSON.parse(e.postData.contents);
    if (!data || !Array.isArray(data.tabs)) throw new Error('tabs 없음');
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    data.tabs.forEach(function (tab, i) { writeTab(ss, tab, i); });
    SpreadsheetApp.flush();
    return reply({ok: true, tabs: data.tabs.length, updated: data.updated || null});
  } catch (err) {
    return reply({ok: false, error: String(err && err.message ? err.message : err)});
  } finally {
    lock.releaseLock();
  }
}

function writeTab(ss, tab, index) {
  var rows = [tab.headers || []].concat(tab.rows || []);
  var width = Math.max(1, rows.reduce(function (w, r) { return Math.max(w, r.length); }, 0));
  var values = rows.map(function (r) {
    var out = r.map(cell);
    while (out.length < width) out.push('');
    return out;
  });
  var sheet = sheetFor(ss, String(tab.name), index);
  sheet.setFrozenRows(0);  // 줄 수를 맞추는 동안은 풀어 둠
  fit(sheet, values.length + 1, width);  // 데이터 + 빈 줄 하나(고정한 줄만 남길 수는 없어서)
  sheet.clear();
  for (var i = 0; i < values.length; i += CHUNK) {
    var part = values.slice(i, i + CHUNK);
    sheet.getRange(i + 1, 1, part.length, width).setValues(part);
  }
  sheet.getRange(1, 1, values.length, width)
    .setVerticalAlignment('top').setWrapStrategy(SpreadsheetApp.WrapStrategy.CLIP);
  (tab.wrap || []).forEach(function (col) {
    if (col >= 1 && col <= width) {
      sheet.getRange(1, col, values.length, 1).setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
    }
  });
  sheet.getRange(1, 1, 1, width).setFontWeight('bold').setBackground(HEADER_COLOR)
    .setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  sheet.setFrozenRows(1);
  (tab.widths || []).forEach(function (w, i) {
    if (i < width && w > 0) sheet.setColumnWidth(i + 1, Math.round(w * 7.5));  // 글자 수 → 픽셀
  });
}

function sheetFor(ss, name, index) {
  var sheet = ss.getSheetByName(name);
  if (sheet) return sheet;
  var all = ss.getSheets();
  // 새 시트에 처음부터 있던 빈 '시트1'은 첫 탭으로 씀
  if (all.length === 1 && all[0].getLastRow() === 0 && all[0].getLastColumn() === 0) return all[0].setName(name);
  return ss.insertSheet(name, Math.min(index, all.length));
}

function fit(sheet, rows, cols) {
  var r = sheet.getMaxRows(), c = sheet.getMaxColumns();
  if (r < rows) sheet.insertRowsAfter(r, rows - r);
  if (r > rows) sheet.deleteRows(rows + 1, r - rows);
  if (c < cols) sheet.insertColumnsAfter(c, cols - c);
  if (c > cols) sheet.deleteColumns(cols + 1, c - cols);
}

function cell(v) {
  if (v === null || v === undefined || v === '') return '';
  if (typeof v === 'number' || typeof v === 'boolean') return v;
  var s = typeof v === 'string' ? v : JSON.stringify(v);
  if (s.length > MAX_CHARS) s = s.slice(0, MAX_CHARS - 1) + '…';
  // 글은 언제나 글 그대로: = + - @ 로 시작하는 말이 수식이 되거나, '10:30'·'1/2' 같은 말이 시각·날짜로 바뀌지 않게
  return "'" + s;
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
