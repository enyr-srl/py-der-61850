import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib
import pytest

from py_der_61850.enyr_61850_2025a.logical_node.FFRC_DAM_2025a import FFRC_DAM_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_LOD_2025a import FFRC_LOD_2025a

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from py_der_61850.enyr_61850_2025a.data_objects.TES_2025a import TES_2025a
from py_der_61850.enyr_61850_2025a.logical_node.FFRC_GN_2025a import FFRC_GN_2025a
from py_der_61850.enyr_61850_2025a.logical_node.pull_dam_ftp import PULL_DAM_FTP
from py_der_61850.enyr_61850_2025a.logical_node.pull_gn_influx import PULL_GN_INFLUXDB
from py_der_61850.enyr_61850_2025a.logical_node.pull_horinsol_influx import PULL_HORINSOL_INFLUXDB
from py_der_61850.enyr_61850_2025a.logical_node.pull_lod_influx import PULL_LOD_INFLUXDB
from py_der_61850.models.config_visitor import ConfigVisitor

# Pulls real data from GME and InfluxDB: excluded by default, run explicitly with `-m integration`.
pytestmark = pytest.mark.integration


class TestFFRCRealWorkflows(unittest.TestCase):
    """Integration-like tests that run pullers + FFRC nodes on real data and create plots for manual inspection."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.results_dir = Path(__file__).parent / "test_results"
        cls.results_dir.mkdir(exist_ok=True)
        for old_plot in cls.results_dir.glob("*.png"):
            try:
                old_plot.unlink()
            except OSError:
                pass

    def test_dam_real_workflow_generates_plot(self) -> None:
        visitor = ConfigVisitor()
        puller = PULL_DAM_FTP(visitor=visitor)
        puller.FrcsRefDAM.setSrcRef = FFRC_DAM_2025a(visitor=visitor)
        puller()
        ffrc = puller.FrcsRefDAM.setSrcRef
        ffrc()

        zone = ffrc.MrkZnIds[0]
        history = ffrc.DamPrcTes[zone]
        forecast = ffrc.DamPrcFrcs[zone]

        self._assert_series_ready(history, f"DAM TES {zone}")
        self._assert_series_ready(forecast, f"DAM FRCS {zone}")

        plot_path = self._build_plot_path(f"ffrc_dam_{zone}")
        self._plot_single_axis(
            history_series=history,
            forecast_series=forecast,
            history_label=f"{zone} TES",
            forecast_label=f"{zone} forecast",
            ylabel="Price [EUR/MWh]",
            title=f"DAM forecast vs TES ({zone})",
            path=plot_path,
            history_span=ffrc.TesSmpNum * ffrc.TesSmpRate,
            forecast_span=ffrc.FrcsSmpNum * ffrc.FrcsSmpRate,
        )

        self.assertTrue(plot_path.exists(), "DAM plot was not created")

    def test_lod_real_workflow_generates_plot(self) -> None:
        visitor = ConfigVisitor()
        puller = PULL_LOD_INFLUXDB(visitor=visitor)
        puller.FrcsRefLOD.setSrcRef = FFRC_LOD_2025a(visitor=visitor)
        puller()
        ffrc = puller.FrcsRefLOD.setSrcRef
        ffrc()

        self.assertGreater(len(ffrc.LodEnTotTes), 0, "LOD TES dictionary is empty")
        user_id = next(iter(ffrc.LodEnTotTes))
        history = ffrc.LodEnTotTes[user_id]
        forecast = ffrc.LodEnTotFrcs[user_id]

        self._assert_series_ready(history, f"LOD TES {user_id}")
        self._assert_series_ready(forecast, f"LOD FRCS {user_id}")

        plot_path = self._build_plot_path(f"ffrc_lod_{user_id}")
        self._plot_single_axis(
            history_series=history,
            forecast_series=forecast,
            history_label=f"{user_id} TES",
            forecast_label=f"{user_id} forecast",
            ylabel="Energy [Wh]",
            title=f"LOD forecast vs TES ({user_id})",
            path=plot_path,
            history_span=ffrc.TesSmpNum * ffrc.TesSmpRate,
            forecast_span=ffrc.FrcsSmpNum * ffrc.FrcsSmpRate,
        )

        self.assertTrue(plot_path.exists(), "LOD plot was not created")

    def test_gn_real_workflow_generates_plot(self) -> None:
        visitor = ConfigVisitor()
        ffrc = FFRC_GN_2025a(visitor=visitor)
        pull_generation = PULL_GN_INFLUXDB(visitor=visitor)
        pull_generation.FrcsRefGN.setSrcRef = ffrc

        pull_insolation = PULL_HORINSOL_INFLUXDB(visitor=visitor)
        pull_insolation.FrcsRefGN.setSrcRef = ffrc
        pull_insolation._user_id = pull_generation._user_id

        pull_insolation()
        pull_generation()
        ffrc()

        user_id = pull_generation._user_id
        self.assertIn(user_id, ffrc.HorInsolTes, f"No irradiance TES data for {user_id}")
        self.assertIn(user_id, ffrc.HorInsolFrcs, f"No irradiance forecast data for {user_id}")
        self.assertIn(user_id, ffrc.GnEnTotTes, f"No generation TES data for {user_id}")
        self.assertIn(user_id, ffrc.GnEnTotFrcs, f"No generation forecast data for {user_id}")
        irradiance_history = ffrc.HorInsolTes[user_id]
        irradiance_forecast = ffrc.HorInsolFrcs[user_id]
        generation_history = ffrc.GnEnTotTes[user_id]
        generation_forecast = ffrc.GnEnTotFrcs[user_id]

        self._assert_series_ready(irradiance_history, f"HorInsol TES {user_id}")
        self._assert_series_ready(irradiance_forecast, f"HorInsol FRCS {user_id}")
        self._assert_series_ready(generation_history, f"Generation TES {user_id}")
        self._assert_series_ready(generation_forecast, f"Generation FRCS {user_id}")

        plot_path = self._build_plot_path(f"ffrc_gn_{user_id}")
        self._plot_generation_axes(
            irradiance_history=irradiance_history,
            irradiance_forecast=irradiance_forecast,
            generation_history=generation_history,
            generation_forecast=generation_forecast,
            path=plot_path,
            user_id=user_id,
            history_span=ffrc.TesSmpNum * ffrc.TesSmpRate,
            forecast_span=ffrc.FrcsSmpNum * ffrc.FrcsSmpRate,
        )

        self.assertTrue(plot_path.exists(), "GN plot was not created")

    def _plot_single_axis(
        self,
        history_series: TES_2025a,
        forecast_series: TES_2025a,
        history_label: str,
        forecast_label: str,
        ylabel: str,
        title: str,
        path: Path,
        history_span: timedelta | None = None,
        forecast_span: timedelta | None = None,
    ) -> None:
        history_points = self._series_points(history_series)
        forecast_points = self._series_points(forecast_series)

        self.assertGreater(len(history_points), 0, f"{history_label} has no samples")
        self.assertGreater(len(forecast_points), 0, f"{forecast_label} has no samples")

        fig, ax = plt.subplots(figsize=(12, 6))
        self._plot_line(ax, history_points, history_label, "tab:blue", "-")
        self._plot_line(ax, forecast_points, forecast_label, "tab:orange", "--")

        xlim_start, xlim_end = self._compute_xlim(
            [history_series],
            [forecast_series],
            history_span=history_span,
            forecast_span=forecast_span,
        )
        ax.set_xlim(xlim_start, xlim_end)

        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xlabel("Time")
        ax.grid(True, which="major", alpha=0.3)
        ax.legend(loc="upper left")
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

        fig.tight_layout()
        fig.savefig(path)  # type: ignore
        plt.close(fig)

    def _plot_generation_axes(
        self,
        irradiance_history: TES_2025a,
        irradiance_forecast: TES_2025a,
        generation_history: TES_2025a,
        generation_forecast: TES_2025a,
        path: Path,
        user_id: str,
        history_span: timedelta | None = None,
        forecast_span: timedelta | None = None,
    ) -> None:
        irr_history_points = self._series_points(irradiance_history)
        irr_forecast_points = self._series_points(irradiance_forecast)
        gen_history_points = self._series_points(generation_history)
        gen_forecast_points = self._series_points(generation_forecast)

        for label, points in [
            (f"Irradiance TES {user_id}", irr_history_points),
            (f"Irradiance FRCS {user_id}", irr_forecast_points),
            (f"Generation TES {user_id}", gen_history_points),
            (f"Generation FRCS {user_id}", gen_forecast_points),
        ]:
            self.assertGreater(len(points), 0, f"{label} has no samples")

        fig, ax_left = plt.subplots(figsize=(12, 6))
        ax_right = ax_left.twinx()

        self._plot_line(ax_left, irr_history_points, f"{user_id} irradiance TES", "tab:orange", "-")
        self._plot_line(ax_left, irr_forecast_points, f"{user_id} irradiance forecast", "tab:red", "--")
        self._plot_line(ax_right, gen_history_points, f"{user_id} generation TES", "tab:green", "-")
        self._plot_line(ax_right, gen_forecast_points, f"{user_id} generation forecast", "tab:purple", "--")

        xlim_start, xlim_end = self._compute_xlim(
            [irradiance_history, generation_history],
            [irradiance_forecast, generation_forecast],
            history_span=history_span,
            forecast_span=forecast_span,
        )
        ax_left.set_xlim(xlim_start, xlim_end)

        ax_left.set_title(f"GN irradiance & generation forecast ({user_id})")
        ax_left.set_ylabel("Irradiance [W/m²]")
        ax_right.set_ylabel("Generation [Wh]")
        ax_left.set_xlabel("Time")
        ax_left.grid(True, which="major", alpha=0.3)
        ax_left.xaxis.set_major_locator(mdates.DayLocator())
        ax_left.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))

        handles, labels = ax_left.get_legend_handles_labels()
        right_handles, right_labels = ax_right.get_legend_handles_labels()
        handles.extend(right_handles)
        labels.extend(right_labels)
        ax_left.legend(handles, labels, loc="upper left")

        fig.tight_layout()
        fig.savefig(path)  # type: ignore
        plt.close(fig)

    def _plot_line(
        self,
        axis: Any,
        points: list[tuple[datetime, Any]],
        label: str,
        color: str,
        linestyle: str,
    ) -> None:
        if not points:
            return
        times = [timestamp for timestamp, _ in points]
        values = [self._to_float(value) for _, value in points]
        axis.plot(times, values, label=label, color=color, linestyle=linestyle, linewidth=1.6)

    def _compute_xlim(
        self,
        history_series_list: list[TES_2025a],
        forecast_series_list: list[TES_2025a],
        history_span: timedelta | None = None,
        forecast_span: timedelta | None = None,
    ) -> tuple[datetime, datetime]:
        now = self._now_for_series(*history_series_list, *forecast_series_list)
        history_span_value = history_span or max(
            (self._series_span(series) for series in history_series_list),
            default=timedelta(),
        )
        forecast_span_value = forecast_span or max(
            (self._series_span(series) for series in forecast_series_list),
            default=timedelta(),
        )
        return now - history_span_value, now + forecast_span_value

    def _series_points(self, series: TES_2025a) -> list[tuple[datetime, Any]]:
        if series.t is None or not series.val:
            return []
        sample_rate = series.smpRate or timedelta(minutes=15)
        current_time = series.t
        points: list[tuple[datetime, Any]] = []
        for value in series.val:
            points.append((current_time, value))
            current_time += sample_rate
        return points

    def _assert_series_ready(self, series: TES_2025a, label: str) -> None:
        self.assertIsInstance(series, TES_2025a, f"{label} is not a TES instance")
        self.assertIsNotNone(series.t, f"{label} is missing start timestamp")
        self.assertGreater(len(series.val), 0, f"{label} has no recorded values")

    def _series_span(self, series: TES_2025a) -> timedelta:
        sample_rate = series.smpRate or timedelta(minutes=15)
        sample_count = max(series.smpNum, len(series.val))
        return sample_rate * sample_count

    def _now_for_series(self, *series: TES_2025a) -> datetime:
        for serie in series:
            if serie.t is not None:
                if serie.t.tzinfo is not None:
                    return datetime.now(serie.t.tzinfo)
                return datetime.now()
        return datetime.now(timezone.utc)

    def _to_float(self, value: Any) -> float:
        if value is None:
            return float("nan")
        try:
            return float(value)
        except (TypeError, ValueError):
            return float("nan")

    def _build_plot_path(self, prefix: str) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{prefix}_{timestamp}.png"
        return self.results_dir / filename


if __name__ == "__main__":
    unittest.main()
