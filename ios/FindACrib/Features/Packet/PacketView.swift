import SwiftUI
import UIKit
import PDFKit
import VisionKit
import MessageUI
import QuickLook
import UniformTypeIdentifiers
import PhotosUI

/// Help me apply (owner, 2026-11-06) and Profile › My documents: one
/// screen. Everything an agent asks for, scanned or picked from Photos or
/// Files, kept ON THIS PHONE (Services/Packet.swift), then emailed to the
/// renter themselves as one PDF to attach when they apply on the agent's
/// site. Find A Crib never sends anything to an agent and never uploads a
/// document (owner: "we might not be able to send these documents on behalf
/// of the user but we can email these documents to the user").
/// Opened for a listing from a Plus member's re-rental card; without one,
/// from Profile.
struct PacketView: View {
    /// The re-rental this was opened for (Help me apply), or nil (Profile).
    var listing: FeaturedListing? = nil

    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(AuthService.self) private var auth
    @State private var packet = Packet.shared
    @State private var editing = false
    @State private var scanFor: Packet.Kind?
    @State private var importFor: Packet.Kind?
    @State private var uploadFor: Packet.Kind?
    @State private var showPhotos = false
    @State private var photoKind: Packet.Kind = .other
    @State private var photoItems: [PhotosPickerItem] = []
    @State private var preview: URL?
    @State private var showForm = false
    @State private var mail: MailDraft?
    @State private var share: URL?
    @State private var confirmErase = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    if let listing { listingCard(listing) }
                    documentsCard
                    extrasCard
                    sendCard
                    if listing == nil {
                        profileCard
                        formCard
                    }
                    Label(listing == nil ? String(localized: "Kept on this phone only. Find A Crib never uploads your documents or sends them to anyone.")
                                         : String(localized: "Saved to your Profile › My documents. They're there for the next apartment too, and you can delete them any time."),
                          systemImage: listing == nil ? "lock.fill" : "person.crop.circle")
                        .font(.se(14)).foregroundStyle(SE.ink2)
                        .padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.lineSoft))
                    Button("Delete my documents", role: .destructive) { confirmErase = true }
                        .font(.se(15, .semibold)).padding(.top, 4)
                        .opacity(packet.isEmpty ? 0 : 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .background(SE.canvas)
            .navigationTitle(listing == nil ? String(localized: "My documents") : String(localized: "Help me apply"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .sheet(isPresented: $editing) { PacketProfileForm() }
            .sheet(item: $scanFor) { k in
                DocumentScanner { images in if !images.isEmpty { packet.add(kind: k, images: images) } }
                    .ignoresSafeArea()
            }
            .confirmationDialog(String(localized: "Add from"), isPresented: Binding(get: { uploadFor != nil }, set: { if !$0 { uploadFor = nil } }), titleVisibility: .visible) {
                Button("Photos") { if let k = uploadFor { photoKind = k; showPhotos = true }; uploadFor = nil }
                Button("Files") { importFor = uploadFor; uploadFor = nil }
            }
            .photosPicker(isPresented: $showPhotos, selection: $photoItems, maxSelectionCount: 8, matching: .images)
            .onChange(of: photoItems) { _, items in
                guard !items.isEmpty else { return }
                let k = photoKind
                Task {
                    var imgs: [UIImage] = []
                    for it in items { if let d = try? await it.loadTransferable(type: Data.self), let img = UIImage(data: d) { imgs.append(img) } }
                    // Several photos of one kind become one document (pay stubs: one page each).
                    if !imgs.isEmpty { packet.add(kind: k, images: imgs) }
                    photoItems = []
                }
            }
            .fileImporter(isPresented: Binding(get: { importFor != nil }, set: { if !$0 { importFor = nil } }),
                          allowedContentTypes: [.pdf, .image]) { result in
                guard let k = importFor, case .success(let url) = result else { return }
                importFile(url, kind: k)
            }
            .sheet(isPresented: $showForm) { FormFillView() }
            .sheet(item: $mail) { m in MailComposer(draft: m).ignoresSafeArea() }
            .sheet(item: Binding(get: { share.map { SharedFile(url: $0) } }, set: { if $0 == nil { share = nil } })) { f in
                ActivitySheet(items: [f.url]).ignoresSafeArea()
            }
            .quickLookPreview($preview)
            .confirmationDialog(String(localized: "Delete your details and every document from this phone?"), isPresented: $confirmErase, titleVisibility: .visible) {
                Button("Delete everything", role: .destructive) { packet.eraseAll() }
            }
            .onAppear { Analytics.shared.track("packet_open", ["for_listing": listing != nil, "docs": packet.docs.count, "ready": packet.readyCount]) }
        }
    }

    // MARK: sections

    private func listingCard(_ f: FeaturedListing) -> some View {
        HStack(spacing: 12) {
            if let u = f.imageURLs.first {
                RemoteImage(url: u).frame(width: 64, height: 64).clipped()
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(f.title.map { "\(f.address), \($0)" } ?? f.address).font(.se(17, .bold)).foregroundStyle(SE.royal).lineLimit(2)
                if let m = f.moneyLine { Text(m.text).font(.se(14)).foregroundStyle(SE.ink2) }
                Text("Listed by \(f.agent)").font(.se(14)).foregroundStyle(SE.ink2)
            }
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.lineSoft))
        .accessibilityElement(children: .combine)
    }

    private var documentsCard: some View {
        card(String(localized: "Your documents")) {
            Text("What agents ask for on an income-restricted apartment. Scan with your camera or pick a photo or file.")
                .font(.se(14)).foregroundStyle(SE.ink3)
            let ready = packet.readyCount, total = Packet.Kind.core.count
            HStack {
                Text("\(ready) of \(total) ready").font(.se(14, .bold))
                Spacer()
                Text("\(Int((Double(ready) / Double(total) * 100).rounded()))%").font(.se(14, .semibold)).foregroundStyle(SE.ink3)
            }
            .accessibilityElement(children: .combine).accessibilityIdentifier("packet-progress")
            ProgressView(value: Double(ready), total: Double(total)).tint(SE.good)
            ForEach(Packet.Kind.core) { k in kindRow(k) }
        }
    }

    private var extrasCard: some View {
        card(String(localized: "If they apply to you")) {
            ForEach(Packet.Kind.ifTheyApply) { k in kindRow(k) }
        }
    }

    /// One kind: what to add, and either Scan / Upload or what's in.
    @ViewBuilder private func kindRow(_ k: Packet.Kind) -> some View {
        let mine = packet.docs.filter { $0.kind == k }
        let pages = packet.pages(k)
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
                Image(systemName: k.icon).font(.system(size: 15, weight: .semibold)).foregroundStyle(SE.royal)
                    .frame(width: 34, height: 34).background(SE.paleBlue).clipShape(RoundedRectangle(cornerRadius: 8))
                VStack(alignment: .leading, spacing: 1) {
                    Text(k.title).font(.se(16, .bold)).foregroundStyle(SE.ink)
                    Text(k == .payStubs && pages > 0 ? String(localized: "\(k.hint) · \(pages) added") : k.hint)
                        .font(.se(13)).foregroundStyle(SE.ink3)
                }
                Spacer(minLength: 6)
                if k == .payStubs && pages > 0 && pages < Packet.payStubsWanted {
                    Text("\(pages) of \(Packet.payStubsWanted)").font(.se(14, .bold)).foregroundStyle(SE.warn)
                } else if packet.isReady(k) {
                    Label("Added", systemImage: "checkmark").font(.se(14, .bold)).foregroundStyle(SE.good)
                }
                if !packet.isReady(k) || (k == .payStubs && pages < Packet.payStubsWanted) || k == .other {
                    addButtons(k)
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("packet-kind-\(k.rawValue)")
            if k == .payStubs && packet.payStubsStale {
                Label("Your newest pay stub is over 60 days old. Most agents want the latest ones.", systemImage: "exclamationmark.triangle.fill")
                    .font(.se(13, .semibold)).foregroundStyle(SE.warn).padding(.leading, 44)
            }
            ForEach(mine) { d in docRow(d) }
        }
        .padding(.vertical, 4)
    }

    private func addButtons(_ k: Packet.Kind) -> some View {
        HStack(spacing: 6) {
            if VNDocumentCameraViewController.isSupported {
                smallButton(String(localized: "Scan"), id: "packet-scan-\(k.rawValue)") { scanFor = k }
            }
            smallButton(String(localized: "Upload"), id: "packet-add-\(k.rawValue)") { uploadFor = k }
        }
    }

    private func smallButton(_ title: String, id: String, _ action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title).font(.se(14, .bold)).foregroundStyle(SE.royal)
                .padding(.horizontal, 10).frame(minHeight: 44)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line).padding(.vertical, 6))
        }
        .buttonStyle(.plain).accessibilityIdentifier(id)
    }

    private func docRow(_ d: Packet.Doc) -> some View {
        HStack {
            Button { preview = packet.url(d) } label: {
                Label(String(localized: "\(d.title) · \(d.pages) pages"), systemImage: "doc.richtext")
                    .font(.se(14)).foregroundStyle(SE.ink2)
            }.buttonStyle(.plain)
            Spacer()
            Button(role: .destructive) { packet.remove(d) } label: { Image(systemName: "trash").foregroundStyle(SE.bad) }
                .buttonStyle(.plain).frame(width: 44, height: 44).accessibilityLabel("Delete \(d.title)")
        }
        .padding(.leading, 44)
    }

    private var sendCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            SEPrimaryButton(title: String(localized: "Email them to me"), icon: "envelope") { emailToMe() }
                .disabled(packet.docs.isEmpty)
                .accessibilityIdentifier("packet-email")
            Text(packet.docs.isEmpty ? String(localized: "Add your documents above. Then we'll put them in one PDF and email it to you.")
                 : listing.map { String(localized: "One PDF with every document, sent to your own email, so it's ready to attach when you apply on \($0.agent)'s site.") }
                    ?? String(localized: "One PDF with every document, sent to your own email, so it's ready to attach to any application."))
                .font(.se(13)).foregroundStyle(SE.ink3)
            HStack(spacing: 12) {
                SEOutlineButton(title: String(localized: "Save PDF"), icon: "square.and.arrow.down") {
                    share = packet.combinedPDF()
                    Analytics.shared.track("packet_save_pdf", ["docs": packet.docs.count])
                }
                .disabled(packet.docs.isEmpty)
                .accessibilityIdentifier("packet-save-pdf")
                if let out = listing?.outboundURL {
                    SEPrimaryButton(title: String(localized: "Apply on their site"), icon: "arrow.up.right") {
                        Analytics.shared.track("outbound", ["kind": "rerental", "agent": listing?.agent ?? "", "href": out.absoluteString, "src": "apply_help"])
                        openURL(out)
                    }
                    .accessibilityIdentifier("packet-apply")
                }
            }
            Text("Applying is free. Never pay anyone to apply — report fee requests to HPD's Inspector General, (212) 825-3502.")
                .font(.se(13)).foregroundStyle(SE.ink3)
        }
    }

    private var profileCard: some View {
        card(String(localized: "About you")) {
            let p = packet.profile
            if p.fullName.isEmpty {
                Text("Your name, contact, address, job and household — typed once, used in every form.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
            } else {
                Text(p.fullName).font(.se(18, .bold))
                Text([p.email, p.phone].filter { !$0.isEmpty }.joined(separator: " · ")).font(.se(15)).foregroundStyle(SE.ink2)
                Text("Household of \(p.householdSize)" + (p.householdIncome.map { String(localized: " · \(Formatters.dollars($0))/yr") } ?? ""))
                    .font(.se(15)).foregroundStyle(SE.ink2)
            }
            SEOutlineButton(title: p.fullName.isEmpty ? String(localized: "Fill in your details") : String(localized: "Edit details"), icon: "person.text.rectangle") { editing = true }
                .accessibilityIdentifier("packet-edit-profile")
        }
    }

    private var formCard: some View {
        card(String(localized: "Fill in an application form")) {
            Text("Got a PDF application from the agent? Open it here and your details go into the matching boxes. You check it, add anything left blank (like your Social Security number) and sign it yourself.")
                .font(.se(15)).foregroundStyle(SE.ink2)
            SEOutlineButton(title: String(localized: "Open a PDF form"), icon: "square.and.pencil") { showForm = true }
                .accessibilityIdentifier("packet-fill-form")
        }
    }

    // MARK: actions

    private func importFile(_ url: URL, kind: Packet.Kind) {
        let ok = url.startAccessingSecurityScopedResource()
        defer { if ok { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url) else { return }
        if UTType(filenameExtension: url.pathExtension)?.conforms(to: .pdf) == true {
            packet.add(kind: kind, pdf: data)
        } else if let img = UIImage(data: data) {
            packet.add(kind: kind, images: [img])
        }
    }

    /// One PDF to the renter's own address: the account's email, else the
    /// one in their details, else blank for them to fill in. Their Mail
    /// sends it; nothing passes through Find A Crib.
    private func emailToMe() {
        guard let pdf = packet.combinedPDF() else { return }
        let me = Self.myEmail(account: auth.email, details: packet.profile.email)
        let subject = listing.map { String(localized: "My application documents — \($0.address)") } ?? String(localized: "My application documents")
        var body = String(localized: "My documents for apartment applications, in one PDF:") + "\n"
        body += packet.docs.map { "• \($0.title)" }.joined(separator: "\n")
        if let l = listing { body += "\n\n" + String(localized: "Apply on \(l.agent)'s site: \(l.outboundURL?.absoluteString ?? l.href)") }
        mail = MailDraft(to: me.map { [$0] } ?? [], subject: subject, body: body,
                         files: [(pdf, String(localized: "My application documents"))])
        Analytics.shared.track("packet_email_me", ["docs": packet.docs.count, "for_listing": listing != nil, "has_address": me != nil])
    }

    static func myEmail(account: String?, details: String) -> String? {
        if let a = account?.trimmingCharacters(in: .whitespaces), a.contains("@") { return a }
        let d = details.trimmingCharacters(in: .whitespaces)
        return d.contains("@") ? d : nil
    }

    private func card<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.se(19, .bold)).foregroundStyle(SE.ink)
            content()
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.lineSoft))
    }
}

/// A file handed to the share sheet (Save PDF).
struct SharedFile: Identifiable { let url: URL; var id: String { url.path } }

struct ActivitySheet: UIViewControllerRepresentable {
    let items: [Any]
    func makeUIViewController(context: Context) -> UIActivityViewController { UIActivityViewController(activityItems: items, applicationActivities: nil) }
    func updateUIViewController(_ c: UIActivityViewController, context: Context) {}
}

// MARK: - Profile form

struct PacketProfileForm: View {
    @Environment(\.dismiss) private var dismiss
    @State private var p = Packet.shared.profile

    var body: some View {
        NavigationStack {
            Form {
                Section("You") {
                    TextField("First name", text: $p.firstName).textContentType(.givenName).accessibilityIdentifier("packet-first")
                    TextField("Last name", text: $p.lastName).textContentType(.familyName)
                    TextField("Email", text: $p.email).textContentType(.emailAddress).keyboardType(.emailAddress).textInputAutocapitalization(.never)
                    TextField("Phone", text: $p.phone).textContentType(.telephoneNumber).keyboardType(.phonePad)
                }
                Section("Current address") {
                    TextField("Street and apartment", text: $p.street).textContentType(.fullStreetAddress)
                    TextField("City", text: $p.city).textContentType(.addressCity)
                    TextField("State", text: $p.state).textContentType(.addressState)
                    TextField("ZIP", text: $p.zip).textContentType(.postalCode).keyboardType(.numberPad)
                    money(String(localized: "Current rent, $/month"), $p.currentRent)
                    TextField("Current landlord or management", text: $p.landlord)
                }
                Section("Work") {
                    TextField("Employer", text: $p.employer).textContentType(.organizationName)
                    TextField("Job title", text: $p.jobTitle).textContentType(.jobTitle)
                    money(String(localized: "Your yearly income, $"), $p.yearlyIncome)
                }
                Section {
                    ForEach($p.others) { $m in
                        VStack(alignment: .leading) {
                            TextField("Name", text: $m.name)
                            TextField("Relationship (e.g. spouse, child)", text: $m.relation)
                            money(String(localized: "Their yearly income, $ (if any)"), $m.yearlyIncome)
                        }
                    }
                    .onDelete { p.others.remove(atOffsets: $0) }
                    Button("Add someone who'll live with you") { p.others.append(.init()) }
                } header: { Text("Household") } footer: {
                    Text("Household of \(p.householdSize). No Social Security numbers or birth dates are kept here — fill those in on the agent's form yourself.")
                }
            }
            .navigationTitle("Your details").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { Packet.shared.update(p); Analytics.shared.track("packet_profile_saved", ["hh": p.householdSize]); dismiss() }
                        .accessibilityIdentifier("packet-save")
                }
            }
        }
    }

    private func money(_ label: String, _ v: Binding<Int?>) -> some View {
        TextField(label, text: Binding(get: { v.wrappedValue.map(String.init) ?? "" },
                                       set: { v.wrappedValue = Int($0.filter(\.isNumber)) }))
            .keyboardType(.numberPad)
    }
}

// MARK: - Fill a PDF form

struct FormFillView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var picking = true
    @State private var doc: PDFDocument?
    @State private var result: (filled: Int, total: Int)?
    @State private var saved: URL?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let doc, let result {
                    Text(result.total == 0
                         ? String(localized: "This PDF has no fillable boxes — print it, or fill it in with Markup.")
                         : String(localized: "Filled \(result.filled) of \(result.total) boxes from your details. Tap any box to change it; add what's blank and sign it yourself."))
                        .font(.se(15)).foregroundStyle(SE.ink2).padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(SE.paleBlue)
                        .accessibilityIdentifier("form-fill-result")
                    PDFKitView(document: doc)
                } else {
                    Spacer()
                    SEOutlineButton(title: String(localized: "Choose a PDF"), icon: "doc") { picking = true }.padding()
                    Spacer()
                }
            }
            .navigationTitle("Application form").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                if doc != nil {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Add to packet") {
                            if let d = doc?.dataRepresentation() { Packet.shared.add(kind: .other, pdf: d, title: String(localized: "Application form")) }
                            dismiss()
                        }
                    }
                }
            }
            .fileImporter(isPresented: $picking, allowedContentTypes: [.pdf]) { r in
                guard case .success(let url) = r else { return }
                let ok = url.startAccessingSecurityScopedResource()
                defer { if ok { url.stopAccessingSecurityScopedResource() } }
                guard let data = try? Data(contentsOf: url), let d = PDFDocument(data: data) else { return }
                result = Packet.fill(d, profile: Packet.shared.profile)
                doc = d
                Analytics.shared.track("packet_form_filled", ["filled": result?.filled ?? 0, "fields": result?.total ?? 0])
            }
        }
    }
}

struct PDFKitView: UIViewRepresentable {
    let document: PDFDocument
    func makeUIView(context: Context) -> PDFView {
        let v = PDFView(); v.autoScales = true; v.document = document; return v
    }
    func updateUIView(_ v: PDFView, context: Context) { if v.document !== document { v.document = document } }
}

// MARK: - Scanner and mail

struct DocumentScanner: UIViewControllerRepresentable {
    let done: ([UIImage]) -> Void
    @Environment(\.dismiss) private var dismiss
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIViewController(context: Context) -> VNDocumentCameraViewController {
        let c = VNDocumentCameraViewController(); c.delegate = context.coordinator; return c
    }
    func updateUIViewController(_ c: VNDocumentCameraViewController, context: Context) {}
    final class Coordinator: NSObject, VNDocumentCameraViewControllerDelegate {
        let parent: DocumentScanner
        init(_ p: DocumentScanner) { parent = p }
        func documentCameraViewController(_ c: VNDocumentCameraViewController, didFinishWith scan: VNDocumentCameraScan) {
            parent.done((0..<scan.pageCount).map { scan.imageOfPage(at: $0) }); parent.dismiss()
        }
        func documentCameraViewControllerDidCancel(_ c: VNDocumentCameraViewController) { parent.dismiss() }
        func documentCameraViewController(_ c: VNDocumentCameraViewController, didFailWithError error: Error) { parent.dismiss() }
    }
}

/// The draft's text for the share sheet, with its subject for Mail-like apps.
final class MailText: NSObject, UIActivityItemSource {
    let text: String, subject: String
    init(text: String, subject: String) { self.text = text; self.subject = subject }
    func activityViewControllerPlaceholderItem(_ c: UIActivityViewController) -> Any { text }
    func activityViewController(_ c: UIActivityViewController, itemForActivityType t: UIActivity.ActivityType?) -> Any? { text }
    func activityViewController(_ c: UIActivityViewController, subjectForActivityType t: UIActivity.ActivityType?) -> String { subject }
}

struct MailDraft: Identifiable {
    let id = UUID()
    let to: [String]
    let subject: String
    let body: String
    let files: [(URL, String)]
}

/// Mail's own composer when there's a Mail account; otherwise the share
/// sheet with the same files (Gmail, Outlook, AirDrop…).
struct MailComposer: UIViewControllerRepresentable {
    let draft: MailDraft
    @Environment(\.dismiss) private var dismiss
    func makeCoordinator() -> Coordinator { Coordinator(self) }
    func makeUIViewController(context: Context) -> UIViewController {
        if MFMailComposeViewController.canSendMail() {
            let m = MFMailComposeViewController()
            m.mailComposeDelegate = context.coordinator
            m.setToRecipients(draft.to); m.setSubject(draft.subject); m.setMessageBody(draft.body, isHTML: false)
            for (url, title) in draft.files {
                if let d = try? Data(contentsOf: url) { m.addAttachmentData(d, mimeType: "application/pdf", fileName: title + ".pdf") }
            }
            return m
        }
        // No Mail account (many people only use the Gmail app): the share
        // sheet with the files. The text carries the subject for apps that
        // ask for one, and the agent's address on its first line, since a
        // share sheet can't fill in the To field.
        let text = (draft.to.isEmpty ? "" : "To: \(draft.to.joined(separator: ", "))\n\n") + draft.body
        let a = UIActivityViewController(activityItems: [MailText(text: text, subject: draft.subject)] + draft.files.map(\.0), applicationActivities: nil)
        a.completionWithItemsHandler = { _, _, _, _ in context.coordinator.parent.dismiss() }
        return a
    }
    func updateUIViewController(_ c: UIViewController, context: Context) {}
    final class Coordinator: NSObject, MFMailComposeViewControllerDelegate {
        let parent: MailComposer
        init(_ p: MailComposer) { parent = p }
        func mailComposeController(_ c: MFMailComposeViewController, didFinishWith result: MFMailComposeResult, error: Error?) {
            let sent = result == .sent
            Task { @MainActor in Analytics.shared.track("packet_email_result", ["sent": sent]); self.parent.dismiss() }
        }
    }
}
