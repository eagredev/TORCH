TestScript_Start::
    lock
    faceplayer
    msgbox TestScript_Text, MSGBOX_DEFAULT
    release
    end

TestScript_Text:
    .string "Hello, this is a test.$"
