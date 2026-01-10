---
tags: 
- cctv
- hikvision
- anpr
- ftp
- alpr
- lpr
description: Suggestions for integrating Hikvision ANPR camera functionality into Home Assistant
---
# ANPR Camera Configuration

## Hikvision

### Example

This example uses the [DS-2CD4A25FWD-IZS](https://specsheets.dvs.co.uk/DS-2CD4A25FWD-IZS.pdf), one of the very first ANPR enabled Hikvision cameras, on its own, without any NVR.

ANPR configuration, including posting images via ftp, is configured in the *Road Traffic* menu under *Advanced*.

![Road Traffic Configuration](assets/images/hik_anpr_menu.png){width=500}

At the bottom of the page is the configuration for actions upon detecting a plate.

![Enable FTP](assets/images/hik_anpr_ftp.png){width=500}

The server name, user name and password, and upload directory for this ftp are set once for all ftp actions in the *Network* menu under *Advanced Configuration*.

![FTP Configuration](assets/images/hik_ftp_config.png){width=500}

### Other Options

* Other Cameras
    - See [Which Hikvision ANPR Camera Should I Buy in 2025?](https://www.use-ip.co.uk/forum/threads/which-hikvision-anpr-camera-should-i-buy-in-2025.12271/) FAQ from [use-IP Forum](https://www.use-ip.co.uk/forum/)
* Other Ways to Integrate
    - Home Assistant built-in [Hikvision Integration](https://www.home-assistant.io/integrations/hikvision/) 
        - Has support for
    'Surveillance Center' notifications but with open [issue #115631](https://github.com/home-assistant/core/issues/115631) for ANPR integration.