// Reminders due today or overdue, as JSON, through EventKit.
//
//   osascript -l JavaScript reminders_today.js
//
// Prints one JSON object:
//   {"status": "ok", "reminders": [{"title", "due", "list"}, ...]}
//   {"status": "denied"}   Reminders access was refused or is restricted.
// Times are local, as YYYY-MM-DDTHH:MM:SS. Reminders with no due date are left out.
//
// EventKit, not AppleScript: scripting Reminders.app needs the Automation
// switch *and* Privacy & Security > Reminders, and AppleScript never shows
// the Reminders prompt, so a refusal there looked like an Automation error.

ObjC.import('EventKit');
ObjC.import('Foundation');

function pad(n) {
  return (n < 10 ? '0' : '') + n;
}

function stamp(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
    'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

function text(value) {
  if (value === undefined || value === null) return '';
  var s = ObjC.unwrap(value);
  return s === undefined || s === null ? '' : String(s);
}

function wait(isDone) {
  var deadline = Date.now() + 25000;
  while (!isDone() && Date.now() < deadline) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.1));
  }
}

function hasAccess(store) {
  // 0 not determined, 1 restricted, 2 denied, 3 full access, 4 write only.
  var status = Number($.EKEventStore.authorizationStatusForEntityType($.EKEntityTypeReminder));
  if (status === 3) return true;
  if (status !== 0) return false;
  var finished = false;
  var granted = false;
  var done = function (ok) {
    granted = !!ok;
    finished = true;
  };
  if (store.respondsToSelector('requestFullAccessToRemindersWithCompletion:')) {
    store.requestFullAccessToRemindersWithCompletion(done);
  } else {
    store.requestAccessToEntityTypeCompletion($.EKEntityTypeReminder, done);
  }
  wait(function () { return finished; });
  return granted;
}

function run(argv) {
  var store = $.EKEventStore.alloc.init;
  if (!hasAccess(store)) return JSON.stringify({status: 'denied'});

  var now = new Date();
  var end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  // JS null reaches EventKit as NSNull and crashes it, so pass real values:
  // the distant past for "overdue too" and every reminder list.
  var predicate = store.predicateForIncompleteRemindersWithDueDateStartingEndingCalendars(
    $.NSDate.distantPast,
    $.NSDate.dateWithTimeIntervalSince1970(end.getTime() / 1000),
    store.calendarsForEntityType($.EKEntityTypeReminder)
  );
  var found = null;
  var finished = false;
  store.fetchRemindersMatchingPredicateCompletion(predicate, function (list) {
    found = list;
    finished = true;
  });
  wait(function () { return finished; });
  if (!finished) return JSON.stringify({status: 'error', error: 'Reminders did not answer'});

  var calendar = $.NSCalendar.currentCalendar;
  var items = [];
  var count = found ? Number(found.count) : 0;
  for (var i = 0; i < count; i++) {
    var r = found.objectAtIndex(i);
    var parts = r.dueDateComponents;
    if (!parts || parts.isNil()) continue;
    var due = calendar.dateFromComponents(parts);
    if (!due || due.isNil()) continue;
    var when = new Date(Number(due.timeIntervalSince1970) * 1000);
    if (when >= end) continue;
    items.push({title: text(r.title), due: stamp(when), list: text(r.calendar.title)});
  }
  return JSON.stringify({status: 'ok', reminders: items});
}
