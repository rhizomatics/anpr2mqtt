# Camera Configuration

## Hikvision

This example uses the [DS-2CD4A25FWD-IZS](https://specsheets.dvs.co.uk/DS-2CD4A25FWD-IZS.pdf), one of the very first ANPR enabled Hikvision cameras.

ANPR configuration, including posting images via ftp, is configured in the *Road Traffic* menu under *Advanced*.

![Road Traffic Configuration](assets/images/hik_anpr_menu.png)

At the bottom of the page is the configuration for actions upon detecting a plate.

![Enable FTP](assets/images/hik_anpr_ftp.png)

The server name, user name and password, and upload directory for this ftp are set once for all ftp actions in the *Network* menu under *Advanced Configuration*.

![FTP Configuration](assets/images/hik_ftp_config.png)