##########
Moneypenny
##########

Moneypenny is an administrative service to provide various provisioning
tasks when users are added to, or removed from, a Rubin Science Platform
instance.  It is derived from ``cachemachine``.


Theory of Operation
===================

Moneypenny presents a standard REST-ful HTTP API with JSON bodies for
individual messages.

A new user provisioning process is created by POSTing a JSON message to
a /moneypenny/<action> endpoint.  The schema is detailed in the
src/moneypenny/schemas directory.

In short, each POST encodes a resource with a username, a UID, and a set
of groupnames mapped to GIDs.  This is used to:

* Create a user home directory with /moneypenny/commission.
* We anticipate that a user directory will eventually be able to be
  removed by sending a POST to /moneypenny/retire.

Getting Started
===============

To start working on this codebase, make a virtualenv and install the
requirements using the Makefile provided by the safir framework.

Moneypenny is developed with the `Safir <https://safir.lsst.io>`__ framework.
`Get started with development with the tutorial <https://safir.lsst.io/set-up-from-template.html>`__.

Further Documentation
=====================

Moneypenny implements the proposal defined in `SQR-052 <https://sqr-052.lsst.io>`__.
