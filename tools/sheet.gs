/** @OnlyCurrentDoc */
// 마롱이 기록 시트. 서버의 tools/report.py --sheet 가 5분마다 탭 내용을 통째로 보내면, 탭마다 지우고 새로 쓴다.
// 시트 메뉴 '마롱이 > 지금 새로고침'을 누르면 부탁을 적어 두고, 서버가 1분마다 물어보고(--if-asked) 가져가서 그때 한 번 더 보낸다.
// 처음 한 번:
//   1. 구글 시트를 새로 만들고 확장 프로그램 > Apps Script 에 이 파일 내용을 그대로 붙여 넣고 저장
//   2. 배포 > 새 배포 > 유형 선택: 웹 앱 / 다음 사용자 인증 정보로 실행: 나 / 액세스 권한이 있는 사용자: 모든 사용자
//      > 배포 > 액세스 승인('확인되지 않은 앱'이 나오면 고급 > 이동 > 허용) > 웹 앱 주소(…/exec) 복사
//   3. 노트북에서 bash deploy/ovh.sh sheet url (주소 붙여넣기) → bash deploy/ovh.sh sheet on
// 웹 앱 주소는 비밀번호와 같다(아는 사람은 이 시트에 쓸 수 있음). 채팅·문서에 붙여 두지 않는다.
// 받은 탭 이름·칸대로 쓰므로 탭이 바뀌어도 이 스크립트는 다시 배포하지 않아도 된다. 받은 적 없는 탭은 건드리지 않는다.
// 줄 색(대화 탭의 친구 말·마롱이 말)은 서버가 줄마다 보낸 대로 칠한다. 시트에 걸어 둔 필터는 새로 채운 뒤 같은 조건으로
// 다시 걸고, 손으로 칠한 색·서식·조건부 서식은 새로 채울 때 지워진다(줄 순서가 바뀌어 엉뚱한 줄에 남지 않게).
// 이 스크립트를 고쳤을 때만: 저장 > 배포 > 배포 관리 > 연필 > 버전: 새 버전 > 배포(주소는 그대로) > 시트 새로 고침(메뉴가 생김).

var MAX_CHARS = 49000;   // 칸 하나는 5만 자까지
var CHUNK = 5000;        // 한 번에 쓰는 줄 수
var HEADER_COLOR = '#e8e3f3';
var COLOR = /^#[0-9a-fA-F]{6}$/;
var WAIT_MS = 150000;    // '지금 새로고침'을 누르고 채워질 때까지 기다리는 시간(서버는 1분마다 물어봄)

function onOpen() {
  SpreadsheetApp.getUi().createMenu('마롱이').addItem('지금 새로고침', 'askRefresh').addToUi();
}

// 메뉴 '지금 새로고침': 부탁 시각을 적어 두고, 서버가 가져가서 다 쓸 때까지 기다렸다가 알려 줌
function askRefresh() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var asked = Date.now();
  PropertiesService.getScriptProperties().setProperty('asked', String(asked));
  ss.toast('서버에 부탁했어요. 1분쯤 뒤에 새로 채워져요.', '마롱이 새로고침', 10);
  for (var waited = 0; waited < WAIT_MS; waited += 5000) {
    Utilities.sleep(5000);
    if (Number(PropertiesService.getScriptProperties().getProperty('done')) >= asked) {
      ss.toast('새로 채웠어요.', '마롱이 새로고침', 5);
      return;
    }
  }
  var taken = !PropertiesService.getScriptProperties().getProperty('asked');
  ss.toast(taken ? '서버가 부탁을 가져갔는데 아직 다 못 썼어요. 조금 뒤에 보거나 다시 눌러 주세요.'
                 : '서버가 부탁을 아직 못 가져갔어요. 웹 앱을 새 버전으로 배포했는지 확인해 주세요.', '마롱이 새로고침', 15);
}

function doPost(e) {
  var data;
  try {
    data = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply({ok: false, error: 'JSON 아님'});
  }
  if (data && data.poll === true) return reply(takeAsk());
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(60000)) return reply({ok: false, error: 'busy'});  // 앞의 갱신이 아직 쓰는 중
  try {
    if (!data || !Array.isArray(data.tabs)) throw new Error('tabs 없음');
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    data.tabs.forEach(function (tab, i) { writeTab(ss, tab, i); });
    SpreadsheetApp.flush();
    PropertiesService.getScriptProperties().setProperty('done', String(Date.now()));  // askRefresh 가 봄
    return reply({ok: true, tabs: data.tabs.length, updated: data.updated || null});
  } catch (err) {
    return reply({ok: false, error: String(err && err.message ? err.message : err)});
  } finally {
    lock.releaseLock();
  }
}

// 서버가 1분마다 물어봄: '지금 새로고침' 부탁이 있으면 그 시각을 넘기면서 지운다(넘긴 뒤 보내기에 실패해도 다시 하지 않음).
// 시트 내용은 돌려주지 않는다
function takeAsk() {
  var props = PropertiesService.getScriptProperties();
  var asked = Number(props.getProperty('asked')) || 0;
  if (asked) props.deleteProperty('asked');
  return {ok: true, asked: asked};
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
  var kept = keepFilter(sheet);  // 걸어 둔 필터는 떼어 두었다가 다 쓰고 다시 검
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
  paint(sheet, tab.colors, values.length - 1, width);
  sheet.getRange(1, 1, 1, width).setFontWeight('bold').setBackground(HEADER_COLOR)
    .setWrapStrategy(SpreadsheetApp.WrapStrategy.WRAP);
  sheet.setFrozenRows(1);
  (tab.widths || []).forEach(function (w, i) {
    if (i < width && w > 0) sheet.setColumnWidth(i + 1, Math.round(w * 7.5));  // 글자 수 → 픽셀
  });
  putFilter(sheet, kept, values.length, width);
}

// 줄마다 바탕색('#rrggbb', 머리줄 아래 첫 줄부터). 색이 없거나 모양이 틀리면 흰색
function paint(sheet, colors, count, width) {
  if (!Array.isArray(colors) || count < 1) return;
  colors = colors.slice(0, count);
  for (var i = 0; i < colors.length; i += CHUNK) {
    var part = colors.slice(i, i + CHUNK).map(function (c) {
      var color = COLOR.test(c) ? c : '#ffffff', row = [];
      for (var j = 0; j < width; j++) row.push(color);
      return row;
    });
    sheet.getRange(i + 2, 1, part.length, width).setBackgrounds(part);
  }
}

// 걸어 둔 필터의 칸별 조건을 기억하고 필터를 뗌. 필터가 없으면 null. 못 떼도 내용 쓰기는 계속함
function keepFilter(sheet) {
  try {
    var filter = sheet.getFilter();
    if (!filter) return null;
    var range = filter.getRange(), kept = {};
    for (var col = range.getColumn(); col <= range.getLastColumn(); col++) {
      var criteria = filter.getColumnFilterCriteria(col);
      if (criteria) kept[col] = criteria.copy().build();
    }
    filter.remove();
    return kept;
  } catch (err) {
    return null;
  }
}

// 새로 쓴 표 전체(머리줄 포함)에 필터를 다시 걸고 기억한 조건을 그대로 넣음
function putFilter(sheet, kept, rows, width) {
  if (!kept) return;
  try {
    var filter = sheet.getRange(1, 1, rows, width).createFilter();
    Object.keys(kept).forEach(function (col) {
      if (Number(col) <= width) filter.setColumnFilterCriteria(Number(col), kept[col]);
    });
  } catch (err) {
    // 필터를 다시 못 걸어도 쓴 내용은 그대로
  }
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
