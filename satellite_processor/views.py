from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from document_processor.models import LandPlot
from .models import SatelliteImage
from .serializers import (
    SatelliteImageSerializer,
    SatellitePreviewRequestSerializer,
)
from .services.planetary import PlanetaryError, save_planetary_preview
from .services.classification import (
    ClassificationError,
    classify_land_plot_by_cadastral_number,
)


@api_view(["POST"])
def fetch_satellite_preview_view(request, cadastral_number: str):
    try:
        land_plot = LandPlot.objects.get(cadastral_number=cadastral_number)
    except LandPlot.DoesNotExist:
        return Response(
            {"detail": "Участок не найден."},
            status=status.HTTP_404_NOT_FOUND,
        )

    request_serializer = SatellitePreviewRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)

    start_date, end_date = request_serializer.get_search_dates()

    try:
        satellite_image = save_planetary_preview(
            land_plot=land_plot,
            start_date=start_date,
            end_date=end_date,
            max_cloud_cover=request_serializer.validated_data.get("max_cloud_cover", 20.0),
            max_snow_ice_percentage=request_serializer.validated_data.get("max_snow_ice_percentage", 20.0),
        )
    except PlanetaryError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return Response(
            {"detail": f"Внутренняя ошибка сервера: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    serializer = SatelliteImageSerializer(
        satellite_image,
        context={"request": request},
    )
    return Response(serializer.data, status=status.HTTP_201_CREATED)


@api_view(["GET"])
def satellite_images_by_cadastral_number_view(request, cadastral_number: str):
    try:
        LandPlot.objects.get(cadastral_number=cadastral_number)
    except LandPlot.DoesNotExist:
        return Response(
            {"detail": "Участок не найден."},
            status=status.HTTP_404_NOT_FOUND,
        )

    images = SatelliteImage.objects.filter(
        land_plot__cadastral_number=cadastral_number
    ).order_by("-acquisition_date", "-created_at")

    serializer = SatelliteImageSerializer(
        images,
        many=True,
        context={"request": request},
    )

    return Response(
        {
            "cadastral_number": cadastral_number,
            "count": images.count(),
            "results": serializer.data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def classify_land_plot_view(request, cadastral_number: str):
    try:
        max_cloud_cover = float(request.data.get("max_cloud_cover", 20.0))
        max_snow_ice_percentage = float(
            request.data.get("max_snow_ice_percentage", 20.0)
        )

        satellite_image = classify_land_plot_by_cadastral_number(
            cadastral_number=cadastral_number,
            max_cloud_cover=max_cloud_cover,
            max_snow_ice_percentage=max_snow_ice_percentage,
        )

        return Response(
            {
                "cadastral_number": cadastral_number,
                "predicted_class": satellite_image.predicted_class,
                "acquisition_date": satellite_image.acquisition_date,
            },
            status=status.HTTP_200_OK,
        )

    except ClassificationError as exc:
        return Response(
            {"detail": str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except ValueError:
        return Response(
            {"detail": "max_cloud_cover и max_snow_ice_percentage должны быть числами."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as exc:
        return Response(
            {"detail": f"Внутренняя ошибка сервера: {exc}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
def satellite_preview_light_view(request, cadastral_number: str):
    try:
        land_plot = LandPlot.objects.get(cadastral_number=cadastral_number)
    except LandPlot.DoesNotExist:
        return Response({"detail": "Участок не найден."}, status=404)

    request_serializer = SatellitePreviewRequestSerializer(data=request.data)
    request_serializer.is_valid(raise_exception=True)

    start_date, end_date = request_serializer.get_search_dates()

    satellite_image = save_planetary_preview(
        land_plot=land_plot,
        start_date=start_date,
        end_date=end_date,
        max_cloud_cover=request_serializer.validated_data.get("max_cloud_cover", 20.0),
        max_snow_ice_percentage=request_serializer.validated_data.get("max_snow_ice_percentage", 20.0),
    )

    return Response({
        "cadastral_number": cadastral_number,
        "acquisition_date": satellite_image.acquisition_date,
        "cloud_cover": satellite_image.cloud_cover,
        "preview_image_url": request.build_absolute_uri(satellite_image.preview_image.url) if satellite_image.preview_image else None,
        "predicted_class": satellite_image.predicted_class,
        "ndvi": satellite_image.ndvi,
    })
