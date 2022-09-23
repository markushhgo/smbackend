from django.contrib.gis.geos import LineString
from django.core.exceptions import ValidationError
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ParseError
from rest_framework.response import Response

from street_maintenance.api.serializers import (
    ActiveEventSerializer,
    HistoryGeometrySerializer,
    MaintenanceUnitSerializer,
    MaintenanceWorkSerializer,
)
from street_maintenance.models import DEFAULT_SRID, MaintenanceUnit, MaintenanceWork


class ActiveEventsViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    queryset = MaintenanceWork.objects.order_by().distinct("events")
    serializer_class = ActiveEventSerializer


class MaintenanceWorkViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = MaintenanceWorkSerializer

    def get_queryset(self):
        queryset = MaintenanceWork.objects.all()
        filters = self.request.query_params

        if "event" in filters:
            queryset = MaintenanceWork.objects.filter(
                events__contains=[filters["event"]]
            )

        if "start_date_time" in filters:
            start_date_time = filters["start_date_time"]
            try:
                queryset = queryset.filter(timestamp__gte=start_date_time)
            except ValidationError:
                return Response(
                    "'start_date_time' must be in format YYYY--MM-DD HH:MM e.g.,'2022-09-18 10:00'",
                    status=status.HTTP_400_BAD_REQUEST,
                )
        return queryset

    def list(self, request):

        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        serializer = self.serializer_class(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["get"])
    def get_geometry_history(self, request):
        # 30 minutes in seconds
        max_work_length = 30 * 60
        if "max_work_length" in request.query_params:
            try:
                max_work_length = int(request.query_params.get("max_work_length"))
            except ValueError:
                raise ParseError("'max_work_length' needs to be of type integer.")
        queryset = self.get_queryset()
        linestrings_list = []
        points_list = []
        unit_ids = (
            queryset.order_by("maintenance_unit_id")
            .values_list("maintenance_unit_id", flat=True)
            .distinct("maintenance_unit_id")
        )
        for unit_id in unit_ids:
            points = []
            qs = queryset.filter(maintenance_unit_id=unit_id).order_by("timestamp")
            prev_timestamp = None
            for elem in qs:
                if prev_timestamp:
                    delta_time = elem.timestamp - prev_timestamp
                    # If delta_time is bigger than the max_work_length, then we cas assume
                    # that the work should not be in the same linestring/point.
                    if delta_time.seconds > max_work_length:
                        if len(points) > 1:
                            linestrings_list.append(
                                LineString(points, srid=DEFAULT_SRID)
                            )
                        else:
                            points_list.append(elem.point)
                        points = []
                points.append(elem.point)
                prev_timestamp = elem.timestamp
            if len(points) > 1:
                linestrings_list.append(LineString(points, srid=DEFAULT_SRID))
            else:
                points_list.append(elem.point)

        data = [{"linestrings": linestrings_list, "points": points_list}]
        results = HistoryGeometrySerializer(data, many=True).data
        return Response(results)


class MaintenanceUnitViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = MaintenanceUnit.objects.all()
    serializer_class = MaintenanceUnitSerializer
