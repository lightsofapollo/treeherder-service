import simplejson as json

from django.http import Http404
from rest_framework import viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from treeherder.model import models

from treeherder.model.derived import (JobsModel, DatasetNotFoundError,
                                      ObjectNotFoundException)


class ObjectstoreViewSet(viewsets.ViewSet):
    """
    This view is responsible for the objectstore endpoint.
    Only create, list and detail will be implemented.
    Update will not be implemented as JobModel will always do
    a conditional create and then an update.
    """

    def create(self, request, project):
        """
        POST method implementation
        """
        jm = JobsModel(project)
        try:
            jm.store_job_data(
                json.dumps(request.DATA),
                request.DATA['job']['job_guid']
            )
        except DatasetNotFoundError as e:
            return Response({"message": str(e)}, status=404)
        except Exception as e:  # pragma nocover
            return Response({"message": str(e)}, status=500)
        finally:
            jm.disconnect()

        return Response({'message': 'well-formed JSON stored'})

    def retrieve(self, request, project, pk=None):
        """
        GET method implementation for detail view
        """
        jm = JobsModel(project)
        obj = jm.get_json_blob_by_guid(pk)
        if obj:
            return Response(json.loads(obj[0]['json_blob']))
        else:
            raise Http404()

    def list(self, request, project):
        """
        GET method implementation for list view
        """
        page = request.QUERY_PARAMS.get('page', 0)
        jm = JobsModel(project)
        objs = jm.get_json_blob_list(page, 10)
        return Response([json.loads(obj['json_blob']) for obj in objs])


class JobsViewSet(viewsets.ViewSet):
    """
    This view is responsible for the jobs endpoint.

    """

    def retrieve(self, request, project, pk=None):
        """
        GET method implementation for detail view
        """
        try:
            jm = JobsModel(project)
            obj = jm.get_job(pk)
        except DatasetNotFoundError as e:
            return Response(
                {"message": "No project with name {0}".format(project)},
                status=404,
            )
        except ObjectNotFoundException as e:
            return Response({"message": unicode(e)}, status=404)
        except Exception as e:  # pragma nocover
            return Response({"message": unicode(e)}, status=500)

        return Response(obj)

    def list(self, request, project):
        """
        GET method implementation for list view
        """
        try:
            page = request.QUERY_PARAMS.get('page', 0)
            jm = JobsModel(project)
            objs = jm.get_job_list(page, 10)
            return Response(objs)
        except DatasetNotFoundError as e:
            return Response({"message": unicode(e)}, status=404)
        except Exception as e:  # pragma nocover
            return Response({"message": unicode(e)}, status=500)
        finally:
            jm.disconnect()

    @action()
    def update_state(self, request, project, pk=None):
        """
        Change the state of a job.
        """
        state = request.DATA.get('state', None)
        jm = JobsModel(project)

        # check that this state is valid
        if state not in jm.STATES:
            return Response(
                {"message": ("'{0}' is not a valid state.  Must be "
                             "one of: {1}".format(
                                 state,
                                 ", ".join(jm.STATES)
                             ))},
                status=400,
            )

        if not pk:  # pragma nocover
            return Response({"message": "job id required"}, status=400)

        try:
            jm.get_job(pk)
            jm.set_state(pk, state)
            jm.disconnect()
        except ObjectNotFoundException as e:
            return Response({"message": unicode(e)}, status=404)
        except Exception as e:  # pragma nocover
            return Response({"message": unicode(e)}, status=500)

        return Response({"message": "state updated to '{0}'".format(state)})


class ResultSetViewSet(viewsets.ViewSet):
    """
    View for ``resultset`` records

    ``result sets`` are synonymous with ``pushes`` in the ui
    """

    def list(self, request, project):
        """
        GET method for list of ``resultset`` records with revisions
        """

        filters = ["author"]

        try:
            page = request.QUERY_PARAMS.get('page', 0)
            jm = JobsModel(project)

            objs = jm.get_result_set_list(
                page,
                1000,
                **dict((k, v) for k, v in request.QUERY_PARAMS.iteritems() if k in filters)
                )
            return Response(objs)
        except DatasetNotFoundError as e:
            return Response({"message": unicode(e)}, status=404)
        except Exception as e:  # pragma nocover
            return Response({"message": unicode(e)}, status=500)
        finally:
            jm.disconnect()

    def get_warning_level(self, groups):
        """
        Return the most severe warning level for a list of jobs.

        A color-based warning level based on the most severe
        level in the list of jobs.

        @@@ - This needs a better way.
        """
        job_states = []
        for group in groups:
            job_states.extend([job["result"] for job in group["jobs"]])

        job_states = set(job_states)
        if "busted" in job_states:
            return "red"
        if "fail" in job_states:
            return "red"
        elif "orange" in job_states:
            return "orange"
        elif "pending" in job_states:
            return "grey"
        elif "retry" in job_states:
            return "grey"
        elif "running" in job_states:
            return "grey"
        else:
            return "green"

    def retrieve(self, request, project, pk=None):
        """
        GET method implementation for detail view of ``resultset``
        """
        filters = ["job_type_name"]

        try:
            jm = JobsModel(project)
            rs = list(jm.get_result_set_by_id(pk))[0]
            jobs_ungrouped = list(jm.get_result_set_job_list(
                pk,
                **dict((k, v) for k, v in request.QUERY_PARAMS.iteritems() if k in filters)
                ))
            # group these by their platforms for return
            jobs_sorted = sorted(jobs_ungrouped, key=lambda x: x["platform"])
            import itertools
            rs["platforms"] = []
            # job_groups by platform
            for k, g in itertools.groupby(jobs_sorted, key=lambda x: x["platform"]):
                job_groups = sorted(list(g), key=lambda x: x["job_group_symbol"])
                groups = []
                for jg_k, jg_g in itertools.groupby(job_groups, key=lambda x: x["job_group_symbol"]):
                    jobs = list(jg_g)
                    groups.append({
                        "symbol": jg_k,
                        "jobs": jobs
                    })
                rs["platforms"].append({
                    "name": k,
                    "groups": groups,
                    "warning_level": self.get_warning_level(groups)
                })

            return Response(rs)
        except DatasetNotFoundError as e:
            return Response(
                {"message": "No project with name {0}".format(project)},
                status=404,
            )
        except ObjectNotFoundException as e:
            return Response({"message": unicode(e)}, status=404)
        except Exception as e:  # pragma nocover
            return Response({"message": unicode(e)}, status=500)
        finally:
            jm.disconnect()


#####################
# Refdata ViewSets
#####################

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata Product model"""
    model = models.Product


class BuildPlatformViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata BuildPlatform model"""
    model = models.BuildPlatform


class OptionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata Option model"""
    model = models.Option


class JobGroupViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata JobGroup model"""
    model = models.JobGroup


class RepositoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata Repository model"""
    model = models.Repository


class MachinePlatformViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata MachinePlatform model"""
    model = models.MachinePlatform


class BugscacheViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata Bugscache model"""
    model = models.Bugscache


class MachineViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata Machine model"""
    model = models.Machine


class MachineNoteViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata MachineNote model"""
    model = models.MachineNote


class RepositoryVersionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata RepositoryVersion model"""
    model = models.RepositoryVersion


class OptionCollectionViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata OptionCollection model"""
    model = models.OptionCollection


class JobTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata JobType model"""
    model = models.JobType


class FailureClassificationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for the refdata FailureClassification model"""
    model = models.FailureClassification