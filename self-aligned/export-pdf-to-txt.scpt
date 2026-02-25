-- Export PDF to Text using Adobe Acrobat Reader
-- Usage: osascript export-pdf-to-txt.scpt /path/to/file.pdf /path/to/output.txt

on run argv
    set pdfPath to item 1 of argv
    set outputPath to item 2 of argv

    -- Get the folder path and filename from outputPath
    set outputFolder to do shell script "dirname " & quoted form of outputPath
    set outputFilename to do shell script "basename " & quoted form of outputPath

    -- Open the PDF in Acrobat Reader
    tell application "Adobe Acrobat Reader"
        activate
        open pdfPath
    end tell

    delay 2 -- Wait for PDF to load

    -- Ensure Acrobat Reader is frontmost before interacting
    tell application "System Events"
        tell process "AdobeReader"
            set frontmost to true
        end tell
    end tell
    delay 0.5

    tell application "System Events"
        tell process "AdobeReader"
            -- Click File > Save as Text...
            click menu item "Save as Text..." of menu "File" of menu bar 1

            delay 1 -- Wait for save dialog

            -- Ensure we're still frontmost after dialog opens
            set frontmost to true
            delay 0.3

            -- Set the filename first (the field should be focused by default)
            set value of text field "Save As:" of window "Save" to outputFilename

            delay 0.3

            -- Click on the dialog to ensure focus before keystrokes
            click window "Save"
            delay 0.2

            -- Use Cmd+Shift+G to open "Go to Folder" dialog
            keystroke "g" using {command down, shift down}
            delay 0.5

            -- Ensure focus before typing path
            set frontmost to true
            delay 0.2

            -- Type the folder path and press enter
            keystroke outputFolder
            delay 0.3
            keystroke return
            delay 1 -- Wait for folder navigation

            -- Click Save button
            click button "Save" of window "Save"
        end tell
    end tell

    delay 2 -- Wait for save to complete

    -- Close the document
    tell application "Adobe Acrobat Reader"
        close front document without saving
    end tell

    -- Convert CR line endings to LF (Acrobat exports with old Mac-style CR)
    do shell script "tr '\\r' '\\n' < " & quoted form of outputPath & " > " & quoted form of outputPath & ".tmp && mv " & quoted form of outputPath & ".tmp " & quoted form of outputPath
end run
