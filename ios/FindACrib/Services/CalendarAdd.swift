import EventKit
import EventKitUI
import SwiftUI

/// "Add to Calendar" (owner, 2026-10-13): lottery deadlines, repair fix-by
/// dates, lease renewal dates. Apple's own event editor runs out of process,
/// so the app never reads the calendar and needs no calendar permission —
/// the person sees the event and taps Add (or Cancel).
struct CalendarItem: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let day: String          // yyyy-MM-dd, an all-day event
    var notes: String? = nil
    var url: URL? = nil
}

struct CalendarAddSheet: UIViewControllerRepresentable {
    let item: CalendarItem
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> EKEventEditViewController {
        let store = EKEventStore()
        let vc = EKEventEditViewController()
        vc.eventStore = store
        let e = EKEvent(eventStore: store)
        e.title = item.title
        e.isAllDay = true
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        let d = f.date(from: item.day) ?? Date()
        e.startDate = d; e.endDate = d
        e.notes = item.notes
        e.url = item.url
        // A nudge the morning before, when there's still time to act.
        e.addAlarm(EKAlarm(relativeOffset: -15 * 3600))
        vc.event = e
        vc.editViewDelegate = context.coordinator
        return vc
    }

    func updateUIViewController(_ vc: EKEventEditViewController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(done: { dismiss() }) }

    final class Coordinator: NSObject, EKEventEditViewDelegate {
        let done: () -> Void
        init(done: @escaping () -> Void) { self.done = done }
        func eventEditViewController(_ controller: EKEventEditViewController, didCompleteWith action: EKEventEditViewAction) {
            let saved = action == .saved
            Task { @MainActor in Analytics.shared.track("calendar_add", ["saved": saved]) }
            done()
        }
    }
}

/// A small "Add to Calendar" button that opens the editor.
struct AddToCalendarButton: View {
    let item: CalendarItem
    var label = "Add to Calendar"
    @State private var showing: CalendarItem?
    var body: some View {
        Button { showing = item } label: { Label(label, systemImage: "calendar.badge.plus").font(.se(16, .semibold)) }
            .sheet(item: $showing) { CalendarAddSheet(item: $0).ignoresSafeArea() }
    }
}
