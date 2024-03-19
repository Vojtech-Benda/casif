import time

import SimpleITK as sitk
import numpy as np
import os
import sys


def getMetricAndErrorsStart():
    global metric_values, multires_iterations, min_values, max_values, mean_values, std_values, error_values, \
        current_iteration

    metric_values = []
    multires_iterations = []
    mean_values = []
    min_values = []
    max_values = []
    std_values = []
    error_values = []
    current_iteration = -1


def getMetricAndErrorsEnd():
    global metric_values, multires_iterations, min_values, max_values, mean_values, std_values, error_values, \
        current_iteration


def getMetricAndErrors(registration_method, fixed_points, moving_points):
    global metric_values, multires_iterations, min_values, max_values, \
        mean_values, std_values, error_values, current_iteration

    if registration_method.GetOptimizerIteration() == current_iteration:
        return

    current_iteration = registration_method.GetOptimizerIteration()
    metric_values.append(registration_method.GetMetricValue())

    current_transform = sitk.CompositeTransform(registration_method.GetInitialTransform())
    current_transform.SetParameters(registration_method.GetOptimizerPosition())
    current_transform.AddTransform(registration_method.GetMovingInitialTransform())
    current_transform.AddTransform(registration_method.GetFixedInitialTransform().GetInverse())

    mean_error, std_error, min_error, max_error, error = getRegistrationErrors(current_transform,
                                                                               fixed_points,
                                                                               moving_points)

    mean_values.append(mean_error)
    min_values.append(min_error)
    max_values.append(max_error)
    std_values.append(std_error)
    error_values.append(error)


def updateMultiresIterations():
    global metric_values, multires_iterations

    multires_iterations.append(len(metric_values))


def getRegistrationErrors(transform, fixed_points, moving_points):
    inverseTransform = transform.GetInverse()
    transformed_points = [transform.TransformPoint(p) for p in fixed_points] # inverseTransform
    errors = [np.linalg.norm(np.array(p_fixed) - np.array(p_moving))
              for p_fixed, p_moving in zip(transformed_points, moving_points)]

    return np.mean(errors), np.std(errors), np.min(errors), np.max(errors), errors


def runGradientDescent(reg_method, fixed_image, moving_image):
    reg_method.SetOptimizerAsGradientDescent(learningRate=1.0,
                                             numberOfIterations=200,
                                             convergenceMinimumValue=1e-5,
                                             convergenceWindowSize=5)

    final_transform = reg_method.Execute(fixed_image, moving_image)
    print(f"Optimizer stop condition: {reg_method.GetOptimizerStopConditionDescription()}")
    print(f" Iteration: {reg_method.GetOptimizerIteration()}")
    print(f" Metric value: {reg_method.GetMetricValue()}")

    return final_transform


def getPoints(path):
    pointList = []
    with open(path, "r") as pointsFile:
        [pointList.append(line.split(",")[1:4]) for line in pointsFile.readlines()[1:]]
        return [[float(coords) for coords in sublist] for sublist in pointList]


def runMain():
    global metric_values, multires_iterations, min_values, max_values, mean_values, std_values, error_values, \
        current_iteration

    if not os.path.exists(inputDir):
        os.makedirs(inputDir)
    print("Loading files...")
    preopDrrPath = os.path.join(inputDir, f"pacient{patientNumber}Preop{view.upper()}.mha")
    intraopDrrPath = os.path.join(inputDir, f"pacient{patientNumber}Intraop{view.upper()}.mha")

    print(preopDrrPath, intraopDrrPath)
    movingImage = sitk.ReadImage(preopDrrPath, sitk.sitkFloat32) # preop image
    fixedImage = sitk.ReadImage(intraopDrrPath, sitk.sitkFloat32) # intraop image

    movingPoints = getPoints(os.path.join(inputDir, f"pacient{patientNumber}PreopPoints{view.upper()}.csv"))
    fixedPoints = getPoints(os.path.join(inputDir, f"pacient{patientNumber}IntraopPoints{view.upper()}.csv"))

    # intraopImageInverted = sitk.InvertIntensity(intraopImage, maximum=1)
    print(f"moving: {movingImage.GetSize()}, fixed: {fixedImage.GetSize()}")

    print("Starting registration...")
    # movingImage.SetOrigin(fixedImage.GetOrigin())
    # movingImage.SetSpacing(fixedImage.GetSpacing())
    print(f"Fixed image, spacing: {fixedImage.GetSpacing()}, size: {fixedImage.GetSize()}, "
          f"direction: {fixedImage.GetDirection()}, origin: {fixedImage.GetOrigin()}")
    print(f"Moving image, spacing: {movingImage.GetSpacing()}, size: {movingImage.GetSize()}, "
          f"direction: {movingImage.GetDirection()}, origin: {movingImage.GetOrigin()}")

    initialTransform = sitk.CenteredTransformInitializer(fixedImage, movingImage,
                                                         sitk.AffineTransform(3),
                                                         sitk.CenteredTransformInitializerFilter.MOMENTS)

    movingInitialImage = sitk.Resample(movingImage, fixedImage, initialTransform, sitk.sitkLinear, 0.0,
                                       movingImage.GetPixelID())

    initialTransformInverse = initialTransform.GetInverse()
    movingInitialPoints = [initialTransformInverse.TransformPoint(p) for p in movingPoints] # initialTransformInverse,
    # movingPoints

    registration = sitk.ImageRegistrationMethod()
    registration.SetMetricAsMattesMutualInformation()
    registration.SetOptimizerScalesFromPhysicalShift()
    registration.SetInitialTransform(initialTransform)
    registration.SetInterpolator(sitk.sitkLinear)
    registration.AddCommand(sitk.sitkStartEvent, getMetricAndErrorsStart)
    registration.AddCommand(sitk.sitkEndEvent, getMetricAndErrorsEnd)
    # registration.AddCommand(sitk.sitkMultiResolutionIterationEvent, updateMultiresIterations)
    registration.AddCommand(sitk.sitkIterationEvent, lambda: getMetricAndErrors(registration,
                                                                                fixedPoints,
                                                                                movingPoints))
    shrinkFactor = []
    smoothSigmas = []
    if multiresLevel > 1:
        print(f"Registering with multiresolution level {multiresLevel}")

        levels = multiresLevel
        shrinkFactor = [2 ** factor for factor in range(0, levels)][::-1]
        smoothSigmas = [factor for factor in range(0, levels)][::-1]

        registration.SetShrinkFactorsPerLevel(shrinkFactors=shrinkFactor)
        registration.SetSmoothingSigmasPerLevel(smoothingSigmas=smoothSigmas)
        registration.SmoothingSigmasAreSpecifiedInPhysicalUnitsOn()
        registration.AddCommand(sitk.sitkMultiResolutionIterationEvent, updateMultiresIterations)

    start_time = time.time()
    match regOptim:
        case "gradient":
            finalTransform = runGradientDescent(registration, fixedImage, movingImage)
        case "reg":
            pass
        case "reg":
            pass
    exec_time = time.time() - start_time
    print(f"Registration time: {exec_time:.3f} seconds")

    final_iter = registration.GetOptimizerIteration()
    print("Resampling transformed image...")
    movingFinalImage = sitk.Resample(movingImage, fixedImage, finalTransform,
                                     sitk.sitkLinear, 0.0, movingImage.GetPixelID())

    finalTransformInverse = finalTransform.GetInverse()
    movingFinalPoints = [finalTransformInverse.TransformPoint(p) for p in movingPoints]

    _, _, _, _, pre_error = getRegistrationErrors(sitk.Transform(), fixedPoints, movingPoints)

    print(f"Mean error values: {mean_values[0], mean_values[-1]}")
    error_values = np.insert(error_values, 0, pre_error, axis=0)
    patientDir = os.path.join(inputDir, f"{regOptim}\\")
    if not os.path.exists(patientDir):
        os.makedirs(patientDir)

    print("Saving images, metrics, errors, points...")
    imagePath = os.path.join(patientDir, f"pacient{patientNumber}Images{view.upper()}.npz")
    # fixedPath = os.path.join(patientDir, f"pacient{patientNumber}fixedImage{view.upper()}.npy")
    # movingPath = os.path.join(patientDir, f"pacient{patientNumber}movingImage{view.upper()}.npy")
    # resampledPath = os.path.join(patientDir, f"pacient{patientNumber}resampledImage{view.upper()}.npy")
    metricsPath = os.path.join(patientDir, f"pacient{patientNumber}registrationInfo{view.upper()}.npz")
    errorsPath = os.path.join(patientDir, f"pacient{patientNumber}ErrorsInfo{view.upper()}.npz")
    pointsPath = os.path.join(patientDir, f"pacient{patientNumber}PointsInfo{view.upper()}.npz")

    # np.save(fixedPath, sitk.GetArrayViewFromImage(fixedImage))
    # np.save(movingPath, sitk.GetArrayViewFromImage(movingImage))
    # np.save(resampledPath, sitk.GetArrayViewFromImage(movingImageResampled))
    np.savez(imagePath, movingImage=sitk.GetArrayFromImage(movingImage)[0, ...],
             fixedImage=sitk.GetArrayFromImage(fixedImage)[0, ...],
             movingInitialImage=sitk.GetArrayFromImage(movingInitialImage)[0, ...],
             movingFinalImage=sitk.GetArrayFromImage(movingFinalImage)[0, ...])

    np.savez(metricsPath, metricValues=metric_values, finalIter=final_iter, multiresIters=multires_iterations,
             shrinkFactors=shrinkFactor, smoothingSigmas=smoothSigmas, execTime=exec_time)
    np.savez(errorsPath, errorValues=error_values, meanValues=mean_values, stdValues=std_values,
             minValues=min_values, maxValues=max_values)
    np.savez(pointsPath, fixedPoints=np.array(fixedPoints), movingPoints=np.array(movingPoints),
             movingInitialPoints=movingInitialPoints, movingFinalPoints=movingFinalPoints)
    print(f"Saved to {patientDir}")
    print("Finished...")


if __name__ == "__main__":

    if len(sys.argv[1:]) == 4:
        patientNumber = sys.argv[1]
        view = sys.argv[2]
        regOptim = sys.argv[3]
        multiresLevel = int(sys.argv[4])
    else:
        print("Použití souboru:\n"
              "argument 1: číslo pacinet - 01, 02, ...\n"
              "argument 2: pohled - ap, lat, pi\n"
              "argument 3: optimalizátor - gradient, \n"
              "argument 4: multires level - 2, 3, ...\n")
        sys.exit(1)

    inputDir = os.path.join(os.getcwd(), f"input_files\\pacient_{patientNumber}\\registration\\")
    runMain()
