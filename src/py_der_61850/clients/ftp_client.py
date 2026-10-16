import io
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from ftplib import FTP_TLS

import pandas as pd


class ImplicitFTP_TLS(FTP_TLS):
    """FTP_TLS subclass that automatically wraps sockets in SSL to support implicit FTPS."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sock = None

    @property
    def sock(self):
        """Return the socket."""
        return self._sock

    @sock.setter
    def sock(self, value):
        """When modifying the socket, ensure that it is ssl wrapped."""
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value)
        self._sock = value


class FtpClient:
    def __init__(self, host: str, user: str, password: str):
        self._user = user
        self._password = password
        self.ftp = ImplicitFTP_TLS()
        self.ftp.set_pasv(True)
        self.ftp.connect(host=host, port=990, timeout=5, source_address=None)

    def _download_file(self, cwd: str, filename: str) -> None:
        self.ftp.cwd(cwd)
        with open(filename, "wb") as f:
            self.ftp.retrbinary("RETR " + filename, f.write)

    def _read_file(self, cwd: str, filename: str) -> bytes:
        buffer = io.BytesIO()
        self.ftp.cwd(cwd)
        self.ftp.retrbinary("RETR " + filename, buffer.write)
        buffer.seek(0)
        self.cwd = cwd
        return buffer.read()

    def close(self):
        self.ftp.quit()

    def get(
        self, cwd: str, date: datetime = datetime.now() - timedelta(days=1), filename: str = "MGPPrezzi.xml"
    ) -> list[dict]:
        self.ftp.login(user=self._user, passwd=self._password)
        self.ftp.prot_p()
        filename = date.strftime("%Y%m%d") + filename

        file = self._read_file(cwd=cwd, filename=filename)
        tree = ET.parse(io.BytesIO(file))
        root = tree.getroot()

        rows = []
        for prezzi in root.findall("Prezzi") or root.findall("Prezzi15"):
            row_data = {}
            for child in prezzi:
                value: float | str = child.text.replace(",", ".") if child.text else ""
                try:
                    value = float(value)
                except ValueError:
                    pass
                row_data[child.tag] = value
            rows.append(row_data)
        return rows

    def convert_date(self, data: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(data)
        df["Data"] = pd.to_datetime(df["Data"].astype(int).astype(str), format="%Y%m%d")
        if "Ora" in df.columns:
            df["Datetime"] = df["Data"] + pd.to_timedelta(df["Ora"].astype(int) - 1, unit="h")
        elif "Periodo" in df.columns:
            df["Datetime"] = df["Data"] + pd.to_timedelta((df["Periodo"].astype(int) - 1) * 15, unit="m")
        return df

    def resample(self, data):
        df = self.convert_date(data)
        df = df.set_index("Datetime").sort_index()
        day = df.index[0].normalize()
        full_index = pd.date_range(day, day + pd.Timedelta("23:45:00"), freq="15min")

        df_resampled = df.resample("15min").ffill()
        df_resampled = df_resampled.reindex(full_index).ffill()

        df_resampled = df_resampled.reset_index().rename(columns={"index": "Datetime"})
        df_resampled.drop(columns=["Data", "Ora"], inplace=True, errors="ignore")
        return df_resampled.to_dict(orient="records")
