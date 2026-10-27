// Today's calendar events as JSON, through EventKit.
//
//   osascript -l JavaScript calendar_today.js '["Work","Home"]'
//
// The optional argument is a JSON list of calendar names; none means all.
// Prints one JSON object:
//   {"status": "ok", "date": "YYYY-MM-DD", "calendars": [...], "events": [...]}
//   {"status": "denied"}   Calendar access was refused or is restricted.
// Times are local, as YYYY-MM-DDTHH:MM:SS.

ObjC.import('EventKit');
ObjC.import('Foundation');

function pad(n) {
  return (n < 10 ? '0' : '') + n;
}

function day(d) {
  return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
}

function stamp(d) {
  return day(d) + 'T' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
}

function text(value) {
  if (value === undefined || value === null) return '';
  var s = ObjC.unwrap(value);
  return s === undefined || s === null ? '' : String(s);
}

function hasAccess(store) {
  // 0 not determined, 1 restricted, 2 denied, 3 authorized (full access),
  // 4 write only.
  var status = Number($.EKEventStore.authorizationStatusForEntityType($.EKEntityTypeEvent));
  if (status === 3) return true;
  if (status !== 0) return false;
  var finished = false;
  var granted = false;
  var done = function (ok) {
    granted = !!ok;
    finished = true;
  };
  if (store.respondsToSelector('requestFullAccessToEventsWithCompletion:')) {
    store.requestFullAccessToEventsWithCompletion(done);
  } else {
    store.requestAccessToEntityTypeCompletion($.EKEntityTypeEvent, done);
  }
  var deadline = Date.now() + 25000;
  while (!finished && Date.now() < deadline) {
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.1));
  }
  return granted;
}

function run(argv) {
  var wanted = argv.length > 0 && argv[0] !== '' ? JSON.parse(argv[0]) : [];
  var store = $.EKEventStore.alloc.init;
  if (!hasAccess(store)) return JSON.stringify({status: 'denied'});

  var all = store.calendarsForEntityType($.EKEntityTypeEvent);
  var names = [];
  var chosen = [];
  for (var i = 0; i < all.count; i++) {
    var cal = all.objectAtIndex(i);
    var name = text(cal.title);
    names.push(name);
    if (wanted.length === 0 || wanted.indexOf(name) >= 0) chosen.push(cal);
  }

  var now = new Date();
  var start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  var end = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  var events = [];
  if (chosen.length > 0) {
    var predicate = store.predicateForEventsWithStartDateEndDateCalendars(
      $.NSDate.dateWithTimeIntervalSince1970(start.getTime() / 1000),
      $.NSDate.dateWithTimeIntervalSince1970(end.getTime() / 1000),
      $(chosen)
    );
    var found = store.eventsMatchingPredicate(predicate);
    for (var j = 0; j < found.count; j++) {
      var ev = found.objectAtIndex(j);
      events.push({
        title: text(ev.title),
        start: stamp(ObjC.unwrap(ev.startDate)),
        end: stamp(ObjC.unwrap(ev.endDate)),
        location: text(ev.location),
        allDay: !!ev.isAllDay,
        calendar: text(ev.calendar.title)
      });
    }
  }
  return JSON.stringify({status: 'ok', date: day(start), calendars: names, events: events});
}
