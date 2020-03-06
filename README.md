## Neato Botvac

Plugin to control internet-connected Neato Botvac vacuums.

First Thing To Know: This plugin uses a 3rd party library which in turn uses the _unofficial_ Neato API.  So it could stop working at any moment with only the dimmest prospects for a fix.

Second Thing To Know: This plugin works via the Neato cloud service.  It won't work without an internet connection and status information is often somewhat delayed.

Third Thing To Know: I have had occasional issues with Neato failing to recognize the plugin's connection as valid.  There's a menu item to reset this, but I haven't been able to isolate the cause and fix it within the plugin.

Fourth Thing To Know: The plugin reproduces all the states and all the commands in the 3rd party library it depends on.  It makes no attempt to determine if any of them are applicable to your model or not.  So a lot of things may simply not work unless your specific machine supports them.

If you're cool with all that, it should be easy to use.  Set up your account credentials in the plugin config, and then create devices for your vacuums. There are a number of actions available.
