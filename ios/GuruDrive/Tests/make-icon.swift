// Code-drawn brand mark. Run with `swift Tests/make-icon.swift` from ios/GuruDrive.
import AppKit
let size = CGSize(width: 1024, height: 1024)
let colorSpace = CGColorSpaceCreateDeviceRGB()
let context = CGContext(data: nil, width: 1024, height: 1024, bitsPerComponent: 8,
                        bytesPerRow: 0, space: colorSpace, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
context.setFillColor(CGColor(red: 0.055, green: 0.035, blue: 0.095, alpha: 1))
context.fill(CGRect(origin: .zero, size: size))
context.setStrokeColor(CGColor(red: 0.69, green: 0.46, blue: 0.93, alpha: 1))
context.setLineWidth(26)
context.strokeEllipse(in: CGRect(x: 140, y: 140, width: 744, height: 744))
context.setFillColor(CGColor(red: 0.17, green: 0.115, blue: 0.25, alpha: 1))
context.addPath(CGPath(roundedRect: CGRect(x: 290, y: 270, width: 444, height: 494), cornerWidth: 150, cornerHeight: 150, transform: nil))
context.fillPath()
context.setShadow(offset: .zero, blur: 45, color: CGColor(red: 0.72, green: 0.41, blue: 1, alpha: 1))
context.setFillColor(CGColor(red: 0.77, green: 0.6, blue: 1, alpha: 1))
context.addPath(CGPath(roundedRect: CGRect(x: 335, y: 535, width: 354, height: 40), cornerWidth: 20, cornerHeight: 20, transform: nil))
context.fillPath()
context.setShadow(offset: .zero, blur: 0)
context.setFillColor(CGColor(red: 0.91, green: 0.77, blue: 0.49, alpha: 1))
context.fillEllipse(in: CGRect(x: 795, y: 725, width: 62, height: 62))
let bitmap = NSBitmapImageRep(cgImage: context.makeImage()!)
try bitmap.representation(using: .png, properties: [:])!.write(to: URL(fileURLWithPath: "GuruDrive/Assets.xcassets/AppIcon.appiconset/AppIcon.png"))
