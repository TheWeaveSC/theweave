# TheWeave demo — query-driven memory retrieval over a plain markdown vault.
# Render with:  PATH=<your-venv>/bin:$PATH vhs docs/theweave-demo.tape
Output docs/theweave-demo.gif
Require weave-cli

Set Shell "bash"
Set FontSize 15
Set Width 1180
Set Height 820
Set Padding 20
Set Theme "Catppuccin Mocha"
Set TypingSpeed 45ms

Hide
Type "export PS1='$ '"
Enter
Type "clear"
Enter
Show

Sleep 600ms
Type "weave-cli demo boot 'ACME cutover with Marcus' 2>/dev/null | head -n 22"
Sleep 800ms
Enter
Sleep 5s
