// Calendar and Reminders access for the app running this, without asking.
//
//   osascript -l JavaScript access_status.js
//
// Prints {"calendar": n, "reminders": n}, where n is EventKit's status:
// 0 not asked yet, 1 restricted, 2 denied, 3 full access, 4 add-only.

ObjC.import('EventKit');

function run(argv) {
  return JSON.stringify({
    calendar: Number($.EKEventStore.authorizationStatusForEntityType($.EKEntityTypeEvent)),
    reminders: Number($.EKEventStore.authorizationStatusForEntityType($.EKEntityTypeReminder))
  });
}
