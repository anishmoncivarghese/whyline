// Render an HTML file to PDF with AppKit. Called as:
//   osascript -l JavaScript html_to_pdf.js <in.html> <out.pdf>
// The text view is 540 points wide. NSPrintInfo saves to the output URL
// with fit-width horizontal pagination and automatic vertical pagination,
// and neither print panel is shown.
ObjC.import("AppKit");

function run(argv) {
    if (!argv || argv.length < 2) {
        throw new Error("usage: html_to_pdf.js <in.html> <out.pdf>");
    }
    var htmlPath = argv[0];
    var pdfPath = argv[1];
    var data = $.NSData.dataWithContentsOfFile(htmlPath);
    if (!data || data.isNil()) {
        throw new Error("cannot read " + htmlPath);
    }

    var options = $.NSMutableDictionary.alloc.init;
    var docType = typeof $.NSHTMLTextDocumentType === "undefined"
        ? "NSHTML"
        : $.NSHTMLTextDocumentType;
    var docKey = typeof $.NSDocumentTypeDocumentAttribute === "undefined"
        ? "DocumentType"
        : $.NSDocumentTypeDocumentAttribute;
    options.setObjectForKey(docType, docKey);

    var error = Ref();
    var attributed = $.NSAttributedString.alloc
        .initWithDataOptionsDocumentAttributesError(data, options, null, error);
    if (!attributed || attributed.isNil()) {
        var why = "HTML did not load";
        if (error[0] && !error[0].isNil() && error[0].localizedDescription) {
            why = error[0].localizedDescription.js;
        }
        throw new Error(why);
    }

    var width = 540;
    var view = $.NSTextView.alloc.initWithFrame($.NSMakeRect(0, 0, width, 100));
    var container = view.textContainer;
    container.setWidthTracksTextView(false);
    container.setHeightTracksTextView(false);
    container.setContainerSize($.NSMakeSize(width, 1.0e7));
    view.setHorizontallyResizable(false);
    view.setVerticallyResizable(true);
    view.setTextContainerInset($.NSMakeSize(0, 0));
    view.textStorage.setAttributedString(attributed);
    var layout = view.layoutManager;
    layout.ensureLayoutForTextContainer(container);
    var used = layout.usedRectForTextContainer(container);
    var height = Math.max(Math.ceil(used.size.height), 100);
    view.setFrame($.NSMakeRect(0, 0, width, height));

    var info = $.NSPrintInfo.sharedPrintInfo.copy;
    var fit = typeof $.NSFitPagination === "undefined" ? 1 : $.NSFitPagination;
    var auto = typeof $.NSAutoPagination === "undefined" ? 0 : $.NSAutoPagination;
    info.setHorizontalPagination(fit);
    info.setVerticalPagination(auto);
    // Shared print info centers a short page, which drops a report into
    // the middle of the sheet. Keep the top margin as the start.
    info.setVerticallyCentered(false);
    info.setHorizontallyCentered(true);
    var saveJob = typeof $.NSPrintSaveJob === "undefined"
        ? "NSPrintSaveJob"
        : $.NSPrintSaveJob;
    info.setJobDisposition(saveJob);
    var saveKey = typeof $.NSPrintJobSavingURL === "undefined"
        ? "NSPrintJobSavingURL"
        : $.NSPrintJobSavingURL;
    info.dictionary.setObjectForKey($.NSURL.fileURLWithPath(pdfPath), saveKey);

    var operation = $.NSPrintOperation.printOperationWithViewPrintInfo(view, info);
    operation.setShowsPrintPanel(false);
    operation.setShowsProgressPanel(false);
    if (!operation.runOperation) {
        throw new Error("PDF print failed");
    }
}
