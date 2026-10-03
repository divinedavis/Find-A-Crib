import SwiftUI
import UIKit
import PDFKit
import VisionKit
import MessageUI
import QuickLook
import UniformTypeIdentifiers

/// "My application packet" — see Services/Packet.swift. Open to everyone
/// (it's a tool, not AI, and paying should never be what gets an
/// application sent). Reached from Profile and from Help me apply.
struct PacketView: View {
    /// When opened for one listing: the agent's document list, address and email.
    var needs: [String] = []
    var listingAddress: String? = nil
    var agentEmail: String? = nil
    var emailSubject: String? = nil
    var emailBody: String? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var packet = Packet.shared
    @State private var editing = false
    @State private var scanFor: Packet.Kind?
    @State private var importFor: Packet.Kind?
    @State private var preview: URL?
    @State private var showForm = false
    @State private var mail: MailDraft?
    @State private var confirmErase = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    intro
                    if !needs.isEmpty { needsCard }
                    profileCard
                    documentsCard
                    formCard
                    sendCard
                    Button("Delete my packet", role: .destructive) { confirmErase = true }
                        .font(.se(15, .semibold)).padding(.top, 4)
                        .opacity(packet.isEmpty ? 0 : 1)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
            }
            .background(SE.canvas)
            .navigationTitle("Application packet").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .sheet(isPresented: $editing) { PacketProfileForm() }
            .sheet(item: $scanFor) { k in
                DocumentScanner { images in if !images.isEmpty { packet.add(kind: k, images: images) } }
                    .ignoresSafeArea()
            }
            .fileImporter(isPresented: Binding(get: { importFor != nil }, set: { if !$0 { importFor = nil } }),
                          allowedContentTypes: [.pdf, .image]) { result in
                guard let k = importFor, case .success(let url) = result else { return }
                importFile(url, kind: k)
            }
            .sheet(isPresented: $showForm) { FormFillView() }
            .sheet(item: $mail) { m in MailComposer(draft: m).ignoresSafeArea() }
            .quickLookPreview($preview)
            .confirmationDialog("Delete your profile and every document in the packet from this phone?", isPresented: $confirmErase, titleVisibility: .visible) {
                Button("Delete everything", role: .destructive) { packet.eraseAll() }
            }
            .onAppear { Analytics.shared.track("packet_open", ["for_listing": listingAddress != nil, "docs": packet.docs.count]) }
        }
    }

    // MARK: sections

    private var intro: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Everything an agent asks for, in one place").font(.se(22, .bold))
            Label("Kept on this phone only — never uploaded to Find A Crib. You send it to the agent yourself.", systemImage: "lock.fill")
                .font(.se(15)).foregroundStyle(SE.ink2)
        }
    }

    private var needsCard: some View {
        card("What this listing asks for") {
            if let a = listingAddress { Text(a).font(.se(15, .semibold)).foregroundStyle(SE.ink3) }
            ForEach(packet.needs(needs)) { n in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: n.have ? "checkmark.circle.fill" : (n.kind == nil ? "circle.dashed" : "circle"))
                        .foregroundStyle(n.have ? SE.good : SE.ink3).font(.system(size: 18))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(n.item).font(.se(16)).foregroundStyle(SE.ink)
                        if !n.have, let k = n.kind {
                            Button("Add \(k.title.lowercased())") { add(k) }.font(.se(14, .semibold)).foregroundStyle(SE.royal)
                        } else if n.kind == nil {
                            Text("From the agent — not something the packet holds").font(.se(13)).foregroundStyle(SE.ink3)
                        }
                    }
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("packet-need")
            }
        }
    }

    private var profileCard: some View {
        card("About you") {
            let p = packet.profile
            if p.fullName.isEmpty {
                Text("Your name, contact, address, job and household — typed once, used in every email and form.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
            } else {
                Text(p.fullName).font(.se(18, .bold))
                Text([p.email, p.phone].filter { !$0.isEmpty }.joined(separator: " · ")).font(.se(15)).foregroundStyle(SE.ink2)
                Text("Household of \(p.householdSize)" + (p.householdIncome.map { " · \(Formatters.dollars($0))/yr" } ?? ""))
                    .font(.se(15)).foregroundStyle(SE.ink2)
            }
            SEOutlineButton(title: p.fullName.isEmpty ? "Fill in your details" : "Edit details", icon: "person.text.rectangle") { editing = true }
                .accessibilityIdentifier("packet-edit-profile")
        }
    }

    private var documentsCard: some View {
        card("Documents") {
            ForEach(Packet.Kind.allCases.filter { $0 != .other }) { k in
                let mine = packet.docs.filter { $0.kind == k }
                HStack(spacing: 12) {
                    Image(systemName: k.icon).font(.system(size: 16, weight: .semibold)).foregroundStyle(SE.royal)
                        .frame(width: 34, height: 34).background(SE.paleBlue).clipShape(Circle())
                    VStack(alignment: .leading, spacing: 2) {
                        Text(k.title).font(.se(16, .semibold))
                        if mine.isEmpty { Text("Not added").font(.se(13)).foregroundStyle(SE.ink3) }
                    }
                    Spacer()
                    Button { add(k) } label: { Image(systemName: "plus.circle.fill").font(.system(size: 24)).foregroundStyle(SE.royal) }
                        .buttonStyle(.plain).frame(width: 44, height: 44)
                        .accessibilityLabel("Add \(k.title)").accessibilityIdentifier("packet-add-\(k.rawValue)")
                }
                ForEach(mine) { d in docRow(d) }
            }
            ForEach(packet.docs.filter { $0.kind == .other }) { d in docRow(d) }
            Button { add(.other) } label: { Label("Add another document", systemImage: "plus") }
                .font(.se(15, .semibold)).foregroundStyle(SE.royal)
        }
    }

    private func docRow(_ d: Packet.Doc) -> some View {
        HStack {
            Button { preview = packet.url(d) } label: {
                Label("\(d.title) · \(d.pages) page\(d.pages == 1 ? "" : "s")", systemImage: "doc.richtext")
                    .font(.se(15)).foregroundStyle(SE.ink)
            }.buttonStyle(.plain)
            Spacer()
            Button(role: .destructive) { packet.remove(d) } label: { Image(systemName: "trash").foregroundStyle(SE.bad) }
                .buttonStyle(.plain).frame(width: 44, height: 44).accessibilityLabel("Delete \(d.title)")
        }
        .padding(.leading, 46)
    }

    private var formCard: some View {
        card("Fill in an application form") {
            Text("Got a PDF application from the agent? Open it here and your details go into the matching boxes. You check it, add anything left blank (like your Social Security number) and sign it yourself.")
                .font(.se(15)).foregroundStyle(SE.ink2)
            SEOutlineButton(title: "Open a PDF form", icon: "square.and.pencil") { showForm = true }
                .accessibilityIdentifier("packet-fill-form")
        }
    }

    private var sendCard: some View {
        card("Send to the agent") {
            Text(packet.docs.isEmpty ? "Add documents above, then email them in one go from your own Mail." :
                    "Emails your \(packet.docs.count) document\(packet.docs.count == 1 ? "" : "s") from your own Mail. Only send what the agent asked for.")
                .font(.se(15)).foregroundStyle(SE.ink2)
            SEPrimaryButton(title: "Email my packet", icon: "paperplane") { compose() }
                .disabled(packet.docs.isEmpty)
                .accessibilityIdentifier("packet-email")
            Text("Applying is free. Never pay anyone to apply — report fee requests to HPD's Inspector General, (212) 825-3502.")
                .font(.se(13)).foregroundStyle(SE.ink3)
        }
    }

    // MARK: actions

    private func add(_ k: Packet.Kind) {
        if VNDocumentCameraViewController.isSupported { scanFor = k } else { importFor = k }
    }

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

    private func compose() {
        let p = packet.profile
        let subject = emailSubject ?? "Application" + (listingAddress.map { " — \($0)" } ?? "")
        var body = emailBody ?? "Hello,\n\nI'd like to apply. My documents are attached.\n\nThank you,\n\(p.fullName)"
        body += "\n\nAttached: " + packet.docs.map(\.title).joined(separator: ", ")
        mail = MailDraft(to: agentEmail.map { [$0] } ?? [], subject: subject, body: body,
                         files: packet.docs.map { (packet.url($0), $0.title) })
        Analytics.shared.track("packet_email", ["docs": packet.docs.count, "for_listing": listingAddress != nil])
    }

    private func card<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.se(19, .bold)).foregroundStyle(SE.ink)
            content()
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(SE.lineSoft))
    }
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
                    money("Current rent, $/month", $p.currentRent)
                    TextField("Current landlord or management", text: $p.landlord)
                }
                Section("Work") {
                    TextField("Employer", text: $p.employer).textContentType(.organizationName)
                    TextField("Job title", text: $p.jobTitle).textContentType(.jobTitle)
                    money("Your yearly income, $", $p.yearlyIncome)
                }
                Section {
                    ForEach($p.others) { $m in
                        VStack(alignment: .leading) {
                            TextField("Name", text: $m.name)
                            TextField("Relationship (e.g. spouse, child)", text: $m.relation)
                            money("Their yearly income, $ (if any)", $m.yearlyIncome)
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
                         ? "This PDF has no fillable boxes — print it, or fill it in with Markup."
                         : "Filled \(result.filled) of \(result.total) boxes from your details. Tap any box to change it; add what's blank and sign it yourself.")
                        .font(.se(15)).foregroundStyle(SE.ink2).padding(12).frame(maxWidth: .infinity, alignment: .leading)
                        .background(SE.paleBlue)
                        .accessibilityIdentifier("form-fill-result")
                    PDFKitView(document: doc)
                } else {
                    Spacer()
                    SEOutlineButton(title: "Choose a PDF", icon: "doc") { picking = true }.padding()
                    Spacer()
                }
            }
            .navigationTitle("Application form").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                if doc != nil {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("Add to packet") {
                            if let d = doc?.dataRepresentation() { Packet.shared.add(kind: .other, pdf: d, title: "Application form") }
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
        let a = UIActivityViewController(activityItems: [draft.body] + draft.files.map(\.0), applicationActivities: nil)
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
